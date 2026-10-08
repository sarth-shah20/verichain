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
from decision_policy import constrain_score, decide

# Pipeline 1 (package imports — ai/ must be on sys.path)
try:
    from pipeline1.classifier import classify as p1_classify
    from pipeline1.provenance.tier0 import run_tier0
    from pipeline1.structure.tier1 import run_tier1
    from pipeline1.pixel_forensics.tier2 import run_tier2
    from pipeline1.tamper_map.tier3 import run_tier3
    from pipeline1.tamper_map.heatmap import generate_heatmap_pages
    from pipeline1.schema import PixelForensicsResult, SuspectRegion
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
    """Run forensics pipeline. Returns a serialisable dict for fusion.

    Adds (additive, fusion-safe):
      - advisory_spectral (Tier 3: spectral corroboration, previously dead code)
      - heatmap_pages: [{page_number, png_bytes, image_w/h, regions[]}] — PNG
        bytes are kept OUT of the fusion dict (binary); process_document lifts
        them out before fusion/store. Only URLs + pct boxes reach the API.
      - suspect_regions: flat pct boxes across pages for the viewer overlay.
    """
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

        # Tier 2 = pixel forensics (copy-move/DCT/ELA/noise/ghost). These are
        # designed for natural photographs and false-positive heavily on typed /
        # born-digital government e-records (repeated glyphs, table grids,
        # seals, uniform fills). Keep their findings for transparency, but mark
        # them ADVISORY so they neither tank the authenticity score nor drive
        # the fused verdict on their own — fusion treats them as low-confidence.
        pixel_result_obj = None
        if tier2 is not None:
            advisory = tier2.model_dump()
            advisory["advisory_note"] = (
                "Pixel forensics (copy-move/DCT/ELA/noise/JPEG-ghost) are unreliable "
                "on typed / born-digital e-records and frequently false-positive on "
                "repeated text, table grids and seals. Treat as advisory, NOT decisive."
            )
            result["advisory_pixel_forensics"] = advisory
            try:
                pixel_result_obj = PixelForensicsResult(**tier2.evidence)
            except Exception:
                pixel_result_obj = None

        # Tier 3 = spectral corroboration (previously wired nowhere). Runs for
        # scans AND born-digital PDFs with embedded images; promotes Tier 2
        # regions it overlaps to high confidence in place.
        tier3 = None
        try:
            tier3 = run_tier3(file_path, classification, pixel_result_obj)
            result["advisory_spectral"] = tier3.model_dump()
            # Propagate corroboration back into the advisory pixel evidence so
            # heatmap boxes + fusion see the promoted confidence.
            if pixel_result_obj is not None and tier3.evidence:
                try:
                    # pixel_result_obj.suspect_regions are already SuspectRegion
                    # objects; tier3 mutated overlapping ones to high in place.
                    merged = list(pixel_result_obj.suspect_regions)
                    seen = {(r.page_number, tuple(r.bbox)) for r in merged}
                    for c in (tier3.evidence.get("corroborated_regions") or []):
                        key = (c.get("page_number"), tuple(c.get("bbox", ())))
                        if key not in seen:
                            from pipeline1.schema import SuspectRegion as _SR

                            merged.append(_SR(**c))
                            seen.add(key)
                    for s in (tier3.evidence.get("suspect_regions") or []):
                        key = (s.get("page_number"), tuple(s.get("bbox", ())))
                        if key not in seen:
                            from pipeline1.schema import SuspectRegion as _SR

                            merged.append(_SR(**s))
                            seen.add(key)
                    # NOTE: TierResult.model_dump() nests the pixel payload under
                    # ["evidence"] — update that path, not the top level.
                    result["advisory_pixel_forensics"]["evidence"]["suspect_regions"] = [
                        r.model_dump() for r in merged
                    ]
                except Exception:
                    pass
        except Exception as exc:
            result["advisory_spectral"] = {"error": str(exc)}

        # Heatmap pages (PNG bytes + pct boxes). Never let render sink the run.
        heatmap_pages: list[dict[str, Any]] = []
        suspect_regions: list[dict[str, Any]] = []
        try:
            from pipeline1.common.page_render import RENDER_ZOOM

            regions_by_page: dict[int, list] = {}
            adv = result.get("advisory_pixel_forensics") or {}
            adv_evidence = adv.get("evidence") or {}
            for r in adv_evidence.get("suspect_regions", []) or []:
                try:
                    sr = SuspectRegion(**r)
                    regions_by_page.setdefault(sr.page_number, []).append(sr)
                except Exception:
                    continue

            # Born-digital / signed PDFs: localized from STRUCTURE (tier1 font +
            # revision boxes, converted from PDF points to render pixels),
            # plus Tier 3 spectral boxes. This is the trustworthy "where edited"
            # signal for typed PDFs where full-page pixel forensics is advisory.
            t1_evidence = {}
            for t in result.get("tiers", []):
                if t.get("name") == "tier1_structure_typography":
                    t1_evidence = t.get("evidence") or {}
                    break
            for sr_dict in t1_evidence.get("structure_regions", []) or []:
                try:
                    pts = sr_dict.get("bbox_pts")
                    page_no = int(sr_dict.get("page_number", 0))
                    page_key = page_no + 1 if page_no == 0 else page_no
                    if not pts:
                        # revision edits without a precise box: use full-page band
                        continue
                    x0, y0, x1, y1 = [float(v) for v in pts]
                    if x1 <= x0 or y1 <= y0:
                        continue
                    z = float(RENDER_ZOOM)
                    boxed = SuspectRegion(
                        page_number=page_key,
                        bbox=(
                            int(round(x0 * z)),
                            int(round(y0 * z)),
                            int(round((x1 - x0) * z)),
                            int(round((y1 - y0) * z)),
                        ),
                        contributing_signals=[sr_dict.get("signal", "structure")],
                        confidence=sr_dict.get("confidence", "medium"),
                        note=sr_dict.get("note", ""),
                    )
                    regions_by_page.setdefault(boxed.page_number, []).append(boxed)
                except Exception:
                    continue

            # Spectral standalone lows also deserve heat tint.
            spec = (result.get("advisory_spectral") or {}).get("evidence") or {}
            for r in spec.get("suspect_regions", []) or []:
                try:
                    sr = SuspectRegion(**r)
                    lst = regions_by_page.setdefault(sr.page_number, [])
                    if all(tuple(x.bbox) != tuple(sr.bbox) for x in lst):
                        lst.append(sr)
                except Exception:
                    continue

            if regions_by_page:
                heatmap_pages = generate_heatmap_pages(file_path, regions_by_page)
                for pg in heatmap_pages:
                    for reg in pg.get("regions", []):
                        suspect_regions.append(
                            {
                                "page": pg["page_number"],
                                "bbox_pct": reg["bbox_pct"],
                                "confidence": reg["confidence"],
                                "signals": reg["signals"],
                                "note": reg["note"],
                            }
                        )
        except Exception:
            heatmap_pages = []
            suspect_regions = []

        result["_heatmap_pages"] = heatmap_pages  # stripped before fusion/store
        result["suspect_regions"] = suspect_regions
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
    return decide(auth_score)


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


def _extract_revision_evidence(forensics_report: dict) -> dict[str, Any] | None:
    """Pull the recovered before/after PDF-revision artifact out of Pipeline 1.

    Tier 1 stores it under evidence.revision_recovery. We surface a compact,
    UI-ready structure ONLY when a material field edit was recovered, so benign
    re-saves never produce a before/after panel.
    """
    for tier in forensics_report.get("tiers", []) or []:
        rr = (tier.get("evidence") or {}).get("revision_recovery")
        if not rr or not rr.get("prior_revision_recovered"):
            continue
        changes = [
            c for c in rr.get("recovered_changes", [])
            if c.get("weight") in ("high", "medium")
        ]
        if not changes:
            continue
        return {
            "detected": True,
            "summary": rr.get("summary"),
            "changes": [
                {
                    "field_hint": c.get("field_hint"),
                    "original_value": c.get("original_value"),
                    "current_value": c.get("current_value"),
                    "kind": c.get("kind"),
                    "weight": c.get("weight"),
                    "page_number": c.get("page_number", 0),
                    "bbox": c.get("bbox"),
                }
                for c in changes
            ],
        }
    return None


def _revision_reason_lines(revision_evidence: dict | None) -> list[str]:
    """Ocrolus-style 'original → edited' lines for the frozen reasons[] list."""
    if not revision_evidence:
        return []
    lines: list[str] = []
    for c in revision_evidence.get("changes", []):
        hint = f"{c['field_hint']} — " if c.get("field_hint") else ""
        lines.append(
            f"Edited PDF field recovered — {hint}original: "
            f"{c['original_value']} → edited: {c['current_value']}"
        )
    return lines


def _holistic_to_api(
    holistic: dict,
    verification_report: dict,
    document_type: str,
    revision_evidence: dict | None = None,
    forensics_report: dict | None = None,
    heatmap_url: str | None = None,
) -> dict[str, Any]:
    """Map a fused holistic report → the frozen API fields (shared by the
    single-doc endpoint and the batch job).

    The fusion LLM emits a risk score (0=clean, 100=fraud); the API contract
    uses an authenticity score (higher=genuine), so we invert.
    """
    fusion = holistic.get("fusion", {})
    raw = fusion.get("overall_risk_score")
    valid = type(raw) is int and 0 <= raw <= 100
    risk_score, policy_reasons = constrain_score(
        100 - raw if valid else None,
        verification_report,
        forensics_report,
        incomplete=bool(fusion.get("fallback")) or not valid,
    )
    route_taken, decision = _decide(risk_score)

    reasons = [
        flag["evidence"]
        for flag in holistic.get("fusion", {}).get("top_flags", [])
    ]
    if not reasons:
        reasons = [holistic.get("fusion", {}).get("rationale", "No specific flags raised.")]
    reasons = list(dict.fromkeys(policy_reasons + reasons))

    # The recovered before/after value is the headline evidence for an edited PDF
    # — surface it first, in both the frozen single-doc reasons[] and the batch.
    revision_lines = _revision_reason_lines(revision_evidence)
    if revision_lines:
        reasons = revision_lines + [r for r in reasons if r not in revision_lines]

    field_ver = _field_verification(verification_report, document_type)
    extracted = verification_report.get("extraction", {}).get("fields", {}) or {}

    api = {
        "risk_score": risk_score,
        "route_taken": route_taken,
        "decision": decision,
        "reasons": reasons,
        "heatmap_url": heatmap_url,
        "field_verification": field_ver.dict(),
        "extracted_fields": extracted,
    }
    # Additive only — the frozen single-doc VerifyResponse ignores unknown keys;
    # the batch job spreads `api` into its per-document result, so this surfaces
    # the before/after panel + viewer overlay boxes there without touching the
    # frozen schema.
    if revision_evidence:
        api["revision_evidence"] = revision_evidence
    if forensics_report is not None:
        suspect = forensics_report.get("suspect_regions") or []
        if suspect:
            api["suspect_regions"] = suspect
            top = next((r for r in suspect if r.get("confidence") == "high"), None)
            if top is None:
                top = next((r for r in suspect if r.get("confidence") == "medium"), None)
            if top is not None:
                api["top_suspect"] = {
                    "confidence": top.get("confidence"),
                    "signals": top.get("signals"),
                    "bbox_pct": top.get("bbox_pct"),
                    "note": top.get("note"),
                }
    return api


def process_document(file_bytes: bytes, document_type: str) -> dict[str, Any]:
    """Run both pipelines + per-document fusion for ONE document.

    Returns the raw pipeline reports (needed for cross-document analysis) plus
    an `api` dict in the frozen contract's field shape. Reused by /verify and
    the batch job — keep it free of HTTP / blockchain concerns.

    Heatmap PNG bytes are returned separately (`heatmap_pages`) so callers can
    persist them to /artifacts and set heatmap_url; they never enter the fusion
    input or the stored job JSON.
    """
    suffix = ".pdf" if file_bytes[:4] == b"%PDF" else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        forensics_report = _run_pipeline1(tmp_path)
        # Binary PNGs must not reach the LLM fusion prompt or the SQLite payload.
        heatmap_pages = forensics_report.pop("_heatmap_pages", []) or []
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

    revision_evidence = _extract_revision_evidence(forensics_report)

    return {
        "verification_report": verification_report,
        "forensics_report": forensics_report,
        "holistic": holistic,
        "revision_evidence": revision_evidence,
        "heatmap_pages": heatmap_pages,
        "api": _holistic_to_api(
            holistic, verification_report, document_type, revision_evidence,
            forensics_report=forensics_report,
        ),
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
    # Persist the first heatmap page for the frozen single-doc contract.
    try:
        import artifacts as _artifacts

        pages = out.get("heatmap_pages") or []
        if pages:
            first = pages[0]
            api["heatmap_url"] = _artifacts.save_single_heatmap(
                out["doc_hash"], first["page_number"], first["png_bytes"]
            )
    except Exception:
        pass
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
