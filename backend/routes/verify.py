"""
POST /verify  — core verification endpoint.

Runs Pipeline 1 (forensics) + Pipeline 2 (content extraction + DB check),
fuses both outputs into a calibrated risk score, logs to the blockchain audit
table, and returns the frozen API contract response.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ── sys.path surgery so flat pipeline2 imports and pipeline1 package imports work ──
_ROOT = Path(__file__).resolve().parents[2]
for _p in [str(_ROOT / "pipeline2"), str(_ROOT / "ai")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Pipeline 2 (flat imports — must come after sys.path)
import pipeline as p2_pipeline  # pipeline2/pipeline.py
import fusion as p2_fusion      # pipeline2/fusion.py

# Pipeline 1 (package imports — ai/ must be on sys.path)
try:
    from pipeline1.classifier import classify as p1_classify
    from pipeline1.provenance.tier0 import run_tier0
    from pipeline1.structure.tier1 import run_tier1
    from pipeline1.pixel_forensics.tier2 import run_tier2
    _P1_AVAILABLE = True
except ImportError:
    _P1_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/verify", tags=["verify"])

_DB_PATH = os.path.abspath(
    os.environ.get(
        "VERICHAIN_DB",
        os.path.join(os.path.dirname(__file__), "..", "..", "verichain.db"),
    )
)

# API contract document_type → pipeline2 schema key
_DOC_TYPE_MAP: dict[str, str | None] = {
    "itr":            "salaried_itr",
    "salary_slip":    "payslip",
    "land_record":    "land_record",   # unified 7/12 · RTC · patta-chitta schema
    "bank_statement": "bank_statement",
    "legal_doc":      None,
}

# Issuer label returned in field_verification.issuer
_ISSUER_MAP: dict[str, str] = {
    "itr":            "CBDT",
    "salary_slip":    "Internal Registry",
    "land_record":    "CERSAI",
    "bank_statement": "Internal Registry",
    "legal_doc":      "Internal Registry",
}


# ─── Request / Response models ────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    applicant_id: str
    document_type: str
    file_base64: str
    digilocker_uri: str | None = None
    ulpin: str | None = None
    has_qr: bool = False


class FieldVerification(BaseModel):
    status: str          # verified | mismatch | unverifiable
    issuer: str
    matched_fields: list[str]


class VerifyResponse(BaseModel):
    risk_score: int
    route_taken: str     # route_1 | route_2 | route_3
    decision: str        # auto_approve | human_review | auto_reject
    reasons: list[str]
    blockchain_tx: str
    heatmap_url: str | None
    field_verification: FieldVerification


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _run_pipeline1(file_path: str) -> dict[str, Any]:
    """Run forensics pipeline. Returns a serialisable dict for fusion."""
    if not _P1_AVAILABLE:
        return {"error": "pipeline1 not available", "tiers": []}

    try:
        classification = p1_classify(file_path)
        tier0 = run_tier0(file_path, classification)
        tier1 = run_tier1(file_path, classification)

        # Tier 2 is pixel forensics — only meaningful for scanned images.
        tier2 = None
        if classification.document_type == "scanned_image":
            tier2 = run_tier2(file_path, classification)

        # Headline authenticity rests on the RELIABLE tiers only: provenance
        # (tier0: signatures/QR/C2PA) and structure (tier1: metadata/fonts).
        reliable = [tier0.model_dump(), tier1.model_dump()]

        result: dict[str, Any] = {
            "classification": classification.model_dump(),
            "tiers": reliable,
            "overall_authenticity_score": min(t["authenticity_score"] for t in reliable),
        }

        # Tier 2 = pixel forensics (copy-move/DCT/ELA). These are designed for
        # natural photographs and false-positive heavily on typed / born-digital
        # government e-records (repeated glyphs, table grids, seals, uniform
        # fills). Keep their findings for transparency, but mark them ADVISORY so
        # they neither tank the authenticity score nor drive the fused verdict on
        # their own — fusion is instructed to treat them as low-confidence.
        if tier2 is not None:
            advisory = tier2.model_dump()
            advisory["advisory_note"] = (
                "Pixel forensics (copy-move/DCT/ELA) are unreliable on typed / "
                "born-digital e-records and frequently false-positive on repeated "
                "text, table grids and seals. Treat as advisory, NOT decisive."
            )
            result["advisory_pixel_forensics"] = advisory

        return result
    except Exception as exc:
        return {"error": str(exc), "tiers": []}


def _decide(auth_score: int) -> tuple[str, str]:
    """Map authenticity score to (route_taken, decision) per API contract.

    The API risk_score is an authenticity/confidence score:
      ≥80 → auto_approve (route_1)
      60-79 → human_review (route_2)
      <60 → auto_reject (route_3)

    This matches the README demo table (APP001 genuine=96→approve, APP002 tampered=18→reject).
    The fusion LLM outputs a risk score (0=clean, 100=fraud) which we invert before routing.
    """
    if auth_score >= 80:
        return "route_1", "auto_approve"
    if auth_score >= 60:
        return "route_2", "human_review"
    return "route_3", "auto_reject"


def _resolve_issuer(verification_report: dict, document_type: str) -> str:
    """Pick the authority label from the DETECTED/verified type, not the request.

    Auto-detected uploads arrive as document_type "unknown", which would wrongly
    fall back to the generic registry label; the real type comes from pipeline2's
    classification and the DB collection it matched against.
    """
    detected = (verification_report.get("document", {}).get("doc_type") or "").lower()
    source = (verification_report.get("database", {}).get("source") or "").lower()
    key = f"{detected} {source}"
    if "itr" in key:
        return "CBDT"
    if any(t in key for t in ("land", "rtc", "patta", "712", "cersai")):
        return "CERSAI"
    return _ISSUER_MAP.get(document_type, "Internal Registry")


def _field_verification(verification_report: dict, document_type: str) -> FieldVerification:
    """Extract field-level verification summary from pipeline2 output."""
    vr = verification_report.get("verification", {})
    match_status = vr.get("match_status", "unverified")

    status_map = {
        "match": "verified",
        "partial_match": "mismatch",
        "mismatch": "mismatch",
        "unverified": "unverifiable",
    }
    status = status_map.get(match_status, "unverifiable")

    matched = [
        fr["field"]
        for fr in vr.get("field_results", [])
        if fr.get("match") is True
    ]

    return FieldVerification(
        status=status,
        issuer=_resolve_issuer(verification_report, document_type),
        matched_fields=matched,
    )


def _log_blockchain(applicant_id: str, doc_hash: str, risk_score: int, decision: str) -> str:
    """Append to blockchain_log and return a mock tx hash."""
    tx_hash = "0x" + hashlib.sha256(f"{applicant_id}{doc_hash}{risk_score}".encode()).hexdigest()[:40]
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "INSERT INTO blockchain_log (applicant_id, doc_hash, risk_score, decision, timestamp, tx_hash) "
            "VALUES (?,?,?,?,?,?)",
            (
                applicant_id, doc_hash, risk_score, decision,
                datetime.now(timezone.utc).isoformat(), tx_hash,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Audit log failure must never break the verification response
    return tx_hash


def _holistic_to_api(
    holistic: dict, verification_report: dict, document_type: str
) -> dict[str, Any]:
    """Map a fused holistic report → the frozen API fields (shared by the
    single-doc endpoint and the batch job).

    The fusion LLM emits a risk score (0=clean, 100=fraud); the API contract
    uses an authenticity score (higher=genuine), so we invert.
    """
    fusion_risk = int(holistic.get("fusion", {}).get("overall_risk_score", 50))
    risk_score = 100 - fusion_risk
    route_taken, decision = _decide(risk_score)

    reasons = [
        flag["evidence"]
        for flag in holistic.get("fusion", {}).get("top_flags", [])
    ]
    if not reasons:
        reasons = [holistic.get("fusion", {}).get("rationale", "No specific flags raised.")]

    field_ver = _field_verification(verification_report, document_type)
    extracted = verification_report.get("extraction", {}).get("fields", {}) or {}

    return {
        "risk_score": risk_score,
        "route_taken": route_taken,
        "decision": decision,
        "reasons": reasons,
        "heatmap_url": None,
        "field_verification": field_ver.dict(),
        "extracted_fields": extracted,
    }


def process_document(file_bytes: bytes, document_type: str) -> dict[str, Any]:
    """Run both pipelines + per-document fusion for ONE document.

    Returns the raw pipeline reports (needed for cross-document analysis) plus
    an `api` dict in the frozen contract's field shape. Reused by /verify and
    the batch job — keep it free of HTTP / blockchain concerns.
    """
    suffix = ".pdf" if file_bytes[:4] == b"%PDF" else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        forensics_report = _run_pipeline1(tmp_path)
        p2_doc_type = _DOC_TYPE_MAP.get(document_type)
        verification_report = p2_pipeline.verify_document_file(
            tmp_path, doc_type=p2_doc_type
        )
        holistic = p2_fusion.fuse_reports(verification_report, forensics_report)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "verification_report": verification_report,
        "forensics_report": forensics_report,
        "holistic": holistic,
        "api": _holistic_to_api(holistic, verification_report, document_type),
        "doc_hash": hashlib.sha256(file_bytes).hexdigest(),
    }


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    try:
        file_bytes = base64.b64decode(req.file_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 in file_base64")

    try:
        out = process_document(file_bytes, req.document_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

    api = out["api"]
    tx_hash = _log_blockchain(
        req.applicant_id, out["doc_hash"], api["risk_score"], api["decision"]
    )

    return VerifyResponse(
        risk_score=api["risk_score"],
        route_taken=api["route_taken"],
        decision=api["decision"],
        reasons=api["reasons"],
        blockchain_tx=tx_hash,
        heatmap_url=api["heatmap_url"],
        field_verification=FieldVerification(**api["field_verification"]),
    )


# ─── History endpoint ─────────────────────────────────────────────────────────

@router.get("/{applicant_id}/history")
def history(applicant_id: str) -> dict:
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT timestamp, doc_hash, risk_score, decision, tx_hash "
            "FROM blockchain_log WHERE applicant_id = ? ORDER BY id DESC",
            (applicant_id,),
        ).fetchall()
        conn.close()
    except Exception:
        rows = []

    return {
        "applicant_id": applicant_id,
        "events": [dict(r) for r in rows],
    }
