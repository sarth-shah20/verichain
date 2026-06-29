"""
POST /verify/batch  — asynchronous, multi-document verification.

The frozen single-doc `/verify` contract (see verify.py) is left untouched. This
ADDS an async batch flow on top of it so the bank UI can submit a whole
applicant file at once and — crucially — run CROSS-DOCUMENT checks (e.g. income
on the salary slip vs. the ITR), which a per-document call can never do because
it never sees the documents together.

Flow:
    POST /verify/batch            -> { job_id }           (returns immediately)
    GET  /verify/batch/{job_id}   -> { status, progress, overall, documents,
                                       cross_document }    (poll until done)

Processing runs in a background thread; the per-document pipelines run
concurrently within it.
"""

from __future__ import annotations

import base64
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import jobs

# Importing verify first runs its sys.path surgery (adds pipeline2/ + ai/),
# so the flat pipeline2 imports below resolve.
from routes.verify import process_document, _decide, _log_blockchain

import discrepancy as p2_discrepancy  # pipeline2/discrepancy.py
import fusion as p2_fusion            # pipeline2/fusion.py


router = APIRouter(prefix="/verify/batch", tags=["verify"])


# ─── Request / Response models ────────────────────────────────────────────────

class BatchDocument(BaseModel):
    document_type: str
    file_base64: str
    filename: str | None = None
    digilocker_uri: str | None = None
    ulpin: str | None = None
    has_qr: bool = False


class BatchVerifyRequest(BaseModel):
    applicant_id: str | None = None
    documents: list[BatchDocument]


class BatchJobResponse(BaseModel):
    job_id: str


# ─── Cross-document mapping ────────────────────────────────────────────────────

def _map_cross(cross_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the pipeline-2 discrepancy report into UI-friendly signals."""
    cross = cross_report.get("cross_document", {})
    out: list[dict[str, Any]] = []
    for d in cross.get("discrepancies", []):
        vals = " vs ".join(str(v) for v in d.get("values", []))
        detail = d.get("detail", "")
        reason = f"{detail} (values: {vals})" if vals else detail
        out.append(
            {
                "label": f"{d.get('attribute', 'Attribute')} differs across documents",
                "reason": reason,
                "severity": d.get("severity", "medium"),
            }
        )
    return out


def _overall_from_holistic(holistic: dict[str, Any]) -> dict[str, Any]:
    """Map a fused holistic report → the overall verdict block (authenticity score)."""
    fusion_risk = int(holistic.get("fusion", {}).get("overall_risk_score", 50))
    risk_score = 100 - fusion_risk
    route_taken, decision = _decide(risk_score)
    reasons = [f["evidence"] for f in holistic.get("fusion", {}).get("top_flags", [])]
    if not reasons:
        reasons = [holistic.get("fusion", {}).get("rationale", "No specific flags raised.")]
    return {
        "risk_score": risk_score,
        "route_taken": route_taken,
        "decision": decision,
        "reasons": reasons,
    }


# ─── Background processing ─────────────────────────────────────────────────────

def _process_one(doc: BatchDocument) -> dict[str, Any]:
    """Verify a single document; never raises (errors become a soft verdict)."""
    try:
        file_bytes = base64.b64decode(doc.file_base64)
        out = process_document(file_bytes, doc.document_type)
        api = out["api"]
        return {
            "ok": True,
            "verification_report": out["verification_report"],
            "doc_hash": out["doc_hash"],
            "doc": {
                "filename": doc.filename or "document",
                "document_type": doc.document_type,
                **api,
            },
        }
    except Exception as exc:  # one bad file must not sink the whole batch
        return {
            "ok": False,
            "verification_report": None,
            "doc_hash": "",
            "doc": {
                "filename": doc.filename or "document",
                "document_type": doc.document_type,
                "risk_score": 50,
                "route_taken": "route_2",
                "decision": "human_review",
                "reasons": [f"Could not process this document: {exc}"],
                "heatmap_url": None,
                "field_verification": {
                    "status": "unverifiable",
                    "issuer": "mock_registry",
                    "matched_fields": [],
                },
                "extracted_fields": {},
            },
        }


def _process_batch(job_id: str, applicant_id: str, documents: list[BatchDocument]) -> None:
    try:
        total = len(documents)
        results: dict[int, dict[str, Any]] = {}

        # 1. Per-document pipelines, concurrently.
        with ThreadPoolExecutor(max_workers=min(4, max(1, total))) as ex:
            futures = {ex.submit(_process_one, d): i for i, d in enumerate(documents)}
            done = 0
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
                done += 1
                jobs.update(job_id, progress=int(done / total * 80))

        ordered = [results[i] for i in range(total)]
        documents_out = [r["doc"] for r in ordered]

        # Blockchain audit log per document.
        for r in ordered:
            d = r["doc"]
            _log_blockchain(applicant_id, r["doc_hash"], d["risk_score"], d["decision"])

        verification_reports = [
            r["verification_report"] for r in ordered if r["ok"] and r["verification_report"]
        ]

        # 2. Cross-document discrepancy analysis (needs ≥2 verifiable docs).
        cross_signals: list[dict[str, Any]] = []
        cross_report = None
        if len(verification_reports) >= 2:
            jobs.update(job_id, progress=88)
            cross_report = p2_discrepancy.find_cross_document_discrepancies(
                verification_reports
            )
            cross_signals = _map_cross(cross_report)

        # 3. Overall fusion across all documents (+ cross-doc).
        jobs.update(job_id, progress=94)
        if verification_reports:
            overall_holistic = p2_fusion.fuse_reports(
                verification_reports,
                {"per_document_forensics": "see individual documents"},
                cross_report,
            )
            overall = _overall_from_holistic(overall_holistic)
        else:
            overall = {
                "risk_score": 50,
                "route_taken": "route_2",
                "decision": "human_review",
                "reasons": ["No documents could be verified."],
            }

        jobs.update(
            job_id,
            status="done",
            progress=100,
            documents=documents_out,
            cross_document=cross_signals,
            overall=overall,
        )
    except Exception as exc:
        jobs.update(job_id, status="error", error=str(exc), progress=100)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=BatchJobResponse)
def create_batch(req: BatchVerifyRequest) -> BatchJobResponse:
    if not req.documents:
        raise HTTPException(status_code=400, detail="No documents supplied.")

    applicant_id = (req.applicant_id or "").strip()
    if not applicant_id:
        applicant_id = f"APP-{uuid.uuid4().hex[:6].upper()}"

    job_id = jobs.create(applicant_id, len(req.documents))
    Thread(
        target=_process_batch,
        args=(job_id, applicant_id, req.documents),
        daemon=True,
    ).start()
    return BatchJobResponse(job_id=job_id)


@router.get("/{job_id}")
def get_batch(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return job
