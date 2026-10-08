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
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

import jobs
import store

# Importing verify first runs its sys.path surgery (adds pipeline2/ + ai/),
# so the flat pipeline2 imports below resolve.
from routes.verify import process_document, _decide, _log_blockchain
import utils as p2_utils

import discrepancy as p2_discrepancy  # pipeline2/discrepancy.py
from decision_policy import constrain_score
from bank_reconciliation import reconcile_salary


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
    demo_scenario: str | None = None


class BatchJobResponse(BaseModel):
    job_id: str


# ─── Cross-document mapping ────────────────────────────────────────────────────

# Period-unit keyword groups used to detect when a discrepancy's raw values are
# expressed in DIFFERENT units (e.g. an annual figure vs a monthly one). Showing
# "370000 (Annual) vs 80000 (Monthly)" side-by-side reads as contradictory, so
# when the units differ we drop the raw tuple and let the narrative carry it.
_PERIOD_UNITS: list[tuple[str, tuple[str, ...]]] = [
    ("annual", ("annual", "annually", "yearly", "per annum", "p.a", "/yr", "/year", "per year")),
    ("monthly", ("monthly", "per month", "/mo", "/month", "p.m")),
    ("quarterly", ("quarterly", "per quarter")),
    ("weekly", ("weekly", "per week")),
    ("daily", ("daily", "per day")),
]


def _unit_of(value: str) -> str | None:
    v = value.lower()
    for name, kws in _PERIOD_UNITS:
        if any(k in v for k in kws):
            return name
    return None


def _units_differ(values: list[Any]) -> bool:
    units = {_unit_of(str(v)) for v in values}
    units.discard(None)
    return len(units) > 1


def _map_cross(cross_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the pipeline-2 discrepancy report into UI-friendly signals."""
    cross = cross_report.get("cross_document", {})
    out: list[dict[str, Any]] = []
    for d in cross.get("discrepancies", []):
        values = d.get("values", []) or []
        vals = " vs ".join(str(v) for v in values)
        detail = d.get("detail", "")
        # Only append the raw values tuple when it aids clarity — i.e. the values
        # share a comparable unit. When units differ, the narrative alone is used.
        if vals and not _units_differ(values):
            reason = f"{detail} (values: {vals})" if detail else f"values: {vals}"
        else:
            reason = detail or f"values: {vals}"
        out.append(
            {
                "label": f"{d.get('attribute', 'Attribute')} differs across documents",
                "reason": reason,
                "severity": d.get("severity", "medium"),
                "source": d.get("source", "model"),
                "check_code": d.get("check_code", "semantic_consistency"),
                "definitive": d.get("definitive", False),
            }
        )
    return out


_DECISION_RANK = {"auto_approve": 1, "human_review": 2, "auto_reject": 3}
_ROUTE_FOR = {
    "auto_approve": "route_1",
    "human_review": "route_2",
    "auto_reject": "route_3",
}


def _overall_from_documents(
    documents_out: list[dict[str, Any]],
    cross_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive the application-level verdict from the per-document results.

    The overall must never look rosier than the worst document, so we take the
    weakest-link authenticity across documents and escalate for cross-document
    fraud (which no single document reveals). This keeps the hero verdict and the
    document cards from contradicting each other.
    """
    if not documents_out:
        return {
            "risk_score": 70,
            "route_taken": "route_2",
            "decision": "human_review",
            "reasons": ["No documents could be verified."],
        }

    min_auth = min(int(d.get("risk_score", 70)) for d in documents_out)

    # Cross-document inconsistency is itself a fraud signal not visible per-doc.
    if min_auth >= 60:
        min_auth, _ = constrain_score(min_auth, [], cross_findings=cross_signals)
    elif any(c.get("definitive") for c in cross_signals):
        min_auth = min(min_auth, 40)

    route_taken, decision = _decide(min_auth)

    # Never less severe than the worst individual document decision.
    worst = max(documents_out, key=lambda d: _DECISION_RANK.get(d.get("decision"), 2))
    if _DECISION_RANK.get(worst.get("decision"), 2) > _DECISION_RANK.get(decision, 2):
        decision = worst["decision"]
        route_taken = _ROUTE_FOR[decision]

    reasons: list[str] = [
        f"{c['label']}: {c['reason']}" if c.get("reason") else c["label"]
        for c in cross_signals
    ]
    reasons += worst.get("reasons", []) or []
    if not reasons:
        reasons = ["All documents are consistent with issuer records of authority."]

    return {
        "risk_score": min_auth,
        "route_taken": route_taken,
        "decision": decision,
        "reasons": reasons[:5],
    }


# ─── Background processing ─────────────────────────────────────────────────────

def _process_one(doc: BatchDocument, on_stage=None) -> dict[str, Any]:
    """Verify a single document; never raises (errors become a soft verdict)."""
    try:
        file_bytes = base64.b64decode(doc.file_base64, validate=True)
        out = process_document(file_bytes, doc.document_type, on_stage=on_stage)
        api = out["api"]
        return {
            "ok": True,
            "verification_report": out["verification_report"],
            "doc_hash": out["doc_hash"],
            "heatmap_pages": out.get("heatmap_pages") or [],
            "preview_pages": out.get("preview_pages") or [],
            "doc": {
                "filename": doc.filename or "document",
                "document_type": out["verification_report"].get("document", {}).get("doc_type", doc.document_type),
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
                "risk_score": 70,
                "route_taken": "route_2",
                "decision": "human_review",
                "reasons": [f"Could not process this document: {exc}"],
                "heatmap_url": None,
                "field_verification": {
                    "status": "unverifiable",
                    "issuer": "Internal Registry",
                    "matched_fields": [],
                },
                "extracted_fields": {},
                "analysis_warnings": ["Document processing could not complete."],
                "analysis_status": "partial",
                "content_status": "unverified",
            },
        }


def _process_batch(job_id: str, applicant_id: str, documents: list[BatchDocument]) -> None:
    try:
        total = len(documents)
        results: dict[int, dict[str, Any]] = {}

        # 1. Per-document pipelines, concurrently.
        with ThreadPoolExecutor(max_workers=min(4, max(1, total))) as ex:
            futures = {ex.submit(_process_one, d, lambda stage, index=i: jobs.set_stage(job_id, index, stage)): i
                       for i, d in enumerate(documents)}
            done = 0
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
                value = results[futures[fut]]
                jobs.set_stage(job_id, futures[fut], "partial" if value["doc"].get("analysis_warnings") else "completed")
                done += 1
                jobs.update(job_id, progress=int(done / total * 80))

        ordered = [results[i] for i in range(total)]
        # Persist heatmap PNGs now that job_id + doc index are known. Binary
        # stays on disk; only the URL travels in the stored job JSON.
        try:
            import artifacts as _artifacts

            for idx, r in enumerate(ordered):
                original_pages = []
                for pg in r.get("preview_pages") or []:
                    url = _artifacts.save_preview(job_id, idx, pg["page_number"], pg["png_bytes"])
                    original_pages.append({"page_number": pg["page_number"], "url": url})
                r["doc"]["page_assets"] = original_pages
                pages = r.get("heatmap_pages") or []
                if not pages:
                    continue
                saved = []
                for pg in pages[:3]:
                    try:
                        url = _artifacts.save_heatmap(
                            job_id, idx, max(1, pg["page_number"]), pg["png_bytes"]
                        )
                        saved.append({"page_number": max(1, pg["page_number"]), "url": url})
                    except Exception:
                        continue
                if saved:
                    r["doc"]["heatmap_url"] = saved[0]["url"]
                    r["doc"]["heatmap_pages"] = saved
        except Exception:
            pass
        documents_out = [r["doc"] for r in ordered]
        for index, doc in enumerate(documents_out):
            doc["doc_id"] = f"doc_{index}"
            for item in doc.get("findings", []):
                item["document_ids"] = [doc["doc_id"]]

        # Blockchain audit log per document.
        for r in ordered:
            d = r["doc"]
            _log_blockchain(applicant_id, r["doc_hash"], d["risk_score"], d["decision"])

        verification_reports = []
        for index, r in enumerate(ordered):
            if r["ok"] and r["verification_report"]:
                r["verification_report"]["_doc_id"] = f"doc_{index}"
                verification_reports.append(r["verification_report"])
        reconciliation = reconcile_salary(verification_reports)

        # 2. Cross-document discrepancy analysis (needs ≥2 verifiable docs).
        cross_signals: list[dict[str, Any]] = []
        cross_report = None
        if len(verification_reports) >= 2:
            jobs.update(job_id, progress=88)
            cross_report = p2_discrepancy.find_cross_document_discrepancies(
                verification_reports
            )
            cross_signals = _map_cross(cross_report)
        for item in reconciliation:
            if item["status"] != "matched":
                cross_signals.append({"label": item["label"], "reason": item["detail"],
                    "severity": item["severity"], "source": "deterministic", "definitive": False,
                    "check_code": item["check_code"], "document_ids": item["document_ids"]})

        # 3. Overall verdict: weakest-link across the per-document results (which
        #    already fuse content + forensics), escalated for cross-document
        #    fraud. Derived from the SAME per-doc verdicts shown on the cards, so
        #    the hero verdict can never contradict the document cards.
        jobs.update(job_id, progress=94)
        overall = _overall_from_documents(documents_out, cross_signals)
        warnings = list((cross_report or {}).get("analysis_warnings", []))
        warnings += [f"{d['filename']}: {w}" for d in documents_out for w in d.get("analysis_warnings", [])]
        if warnings and overall["risk_score"] >= 80:
            overall["risk_score"] = 79
            overall["route_taken"], overall["decision"] = _decide(79)
        if warnings:
            overall["reasons"] = warnings + overall["reasons"]

        jobs.update(
            job_id,
            status="done",
            progress=100,
            documents=documents_out,
            cross_document=cross_signals,
            overall=overall,
            analysis_warnings=warnings,
            analysis_status="partial" if warnings else "complete",
            reconciliation=reconciliation,
        )
        # Persist the completed verification so it survives restart, can be
        # reopened by job_id, and shows up in the History page.
        completed = jobs.get(job_id)
        if completed:
            store.save(completed)
    except Exception as exc:
        jobs.update(job_id, status="error", error=str(exc), progress=100)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=BatchJobResponse)
def create_batch(req: BatchVerifyRequest) -> BatchJobResponse:
    if not req.documents:
        raise HTTPException(status_code=400, detail="No documents supplied.")
    demo = None
    if req.demo_scenario:
        from routes.demo import scenario
        demo = scenario(req.demo_scenario)
    for doc in req.documents:
        try:
            p2_utils.inspect_input(base64.b64decode(doc.file_base64, validate=True))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{doc.filename or 'Document'}: {exc}") from exc

    applicant_id = (req.applicant_id or "").strip()
    if not applicant_id:
        applicant_id = f"APP-{uuid.uuid4().hex[:6].upper()}"

    job_id = jobs.create(applicant_id, len(req.documents))
    jobs.update(job_id, demo_scenario=demo, document_stages=[{"filename": d.filename or "document", "stage": "queued"}
                                        for d in req.documents])
    Thread(
        target=_process_batch,
        args=(job_id, applicant_id, req.documents),
        daemon=True,
    ).start()
    return BatchJobResponse(job_id=job_id)


class DecisionRequest(BaseModel):
    decision: str  # "approved" | "review" | "rejected"
    note: str | None = None


_VALID_DECISIONS = {"approved", "review", "rejected"}


@router.get("/{job_id}")
def get_batch(job_id: str, response: Response) -> dict[str, Any]:
    # Polled every ~600ms; must never be cached or the client can replay a stale
    # "processing" body and hang at 100% after the job is already "done".
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    job = jobs.get(job_id)
    if job is not None:
        return job
    # Not in memory (e.g. after a restart) — fall back to the persistent store so
    # a history report can still be reopened.
    persisted = store.get(job_id)
    if persisted is not None:
        return persisted
    raise HTTPException(status_code=404, detail="Unknown job id.")


@router.get("/{job_id}/report.pdf")
def export_report(job_id: str):
    """Printable/audit PDF for one verification (additive route)."""
    job = jobs.get(job_id) or store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    try:
        import artifacts as _a

        out_dir = _a.ensure_dir(job_id)
        out_path = out_dir / "report.pdf"
        _render_report_pdf(job, str(out_path))
        from fastapi.responses import FileResponse

        return FileResponse(str(out_path), media_type="application/pdf", filename=f"verichain_{job_id}_report.pdf")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report failed: {exc}")


def _render_report_pdf(job: dict[str, Any], out_path: str) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 50.0

    def line(text: str, size: float = 10, bold: bool = False):
        nonlocal y, page
        try:
            # Wrap before truncating — no mid-word chopping, and long reason
            # lists flow onto continued lines instead of disappearing.
            parts = [text[i : i + 90] for i in range(0, len(text), 90)] or [""]
            for p in parts:
                if y > 780:
                    page = doc.new_page()
                    y = 50.0
                try:
                    page.insert_text((50, y), p, fontsize=size, fontname="helv" if not bold else "helv-bold")
                except Exception:
                    page.insert_text((50, y), p, fontsize=size)
                y += size + 8
        except Exception:
            y += size + 8

    line("VeriChain — Verification Report", 16, True)
    y += 6
    line(f"Application: {job.get('applicant_id', '—')}  |  Docs: {job.get('document_count', 0)}", 10)
    line(f"Submitted: {job.get('submitted_at', '—')}", 10)
    ov = job.get("overall") or {}
    line(f"Overall: risk {ov.get('risk_score', '—')} | {ov.get('decision', '—')} | {ov.get('route_taken', '')}", 11, True)
    y += 4
    line("Top reasons:", 11, True)
    for r in (ov.get("reasons") or [])[:5]:
        line(f"  • {r}", 9)
    if job.get("cross_document"):
        y += 4
        line("Cross-document findings:", 11, True)
        for c in job["cross_document"][:6]:
            line(f"  • [{c.get('severity','?')}] {c.get('label')}", 9)
    y += 4
    line("Documents:", 11, True)
    for d in job.get("documents", [])[:8]:
        line(f"  • {d.get('filename','doc')} — {d.get('document_type','?')} — score {d.get('risk_score','?')} ({d.get('decision','?')})", 9)
        ev = (d.get("extracted_fields") or {})
        if ev:
            try:
                sample = ", ".join(f"{k}={v}" for k, v in list(ev.items())[:5])
                line(f"      fields: {sample}", 8)
            except Exception:
                pass
    # Embed first heatmap per document when present.
    for d in job.get("documents", [])[:4]:
        url = d.get("heatmap_url")
        if not url:
            continue
        rel = url.lstrip("/")
        base = os.path.dirname(os.path.abspath(__file__))
        fs_path = os.path.normpath(os.path.join(base, "..", rel.replace("artifacts", "artifacts", 1)))
        # artifacts live under backend/artifacts
        candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *rel.split("/")[1:])
        candidate = os.path.normpath(candidate)
        for p in (candidate, fs_path):
            if os.path.exists(p):
                try:
                    hp = doc.new_page()
                    hp.insert_text((50, 40), f"Heatmap — {d.get('filename','doc')}", fontsize=10, fontname="helv-bold")
                    hp.insert_image(fitz.Rect(50, 60, 545, 760), filename=p)
                except Exception:
                    pass
                break
    doc.save(out_path)
    doc.close()


@router.post("/{job_id}/decision")
def record_decision(job_id: str, req: DecisionRequest) -> dict[str, Any]:
    """Record the underwriter's final decision (persisted + written to audit log)."""
    if req.decision not in _VALID_DECISIONS:
        raise HTTPException(status_code=400, detail="Invalid decision.")
    if not req.note or not req.note.strip():
        raise HTTPException(status_code=400, detail="A reviewer note is required.")
    result = store.record_decision(job_id, req.decision, req.note)
    if result is None:
        raise HTTPException(status_code=404, detail="Verification not found.")
    # Keep the in-memory job (if still live) in sync so a poll reflects it.
    jobs.update(job_id, underwriter_decision=req.decision, reviewer_note=req.note.strip())
    return {"recorded": True, "job_id": job_id, **result}
