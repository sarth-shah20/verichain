"""
In-process job store for asynchronous batch verification.

A batch job verifies several documents for one applicant concurrently, then runs
cross-document analysis. Because the documents are processed in a background
thread, the HTTP layer needs somewhere to read job state from while polling —
that is this module.

This is deliberately simple (a dict guarded by a lock, process-lifetime only).
A production deployment would back this with Redis / a table; the demo does not
need durability across restarts.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(applicant_id: str, document_count: int) -> str:
    """Register a new job in the 'processing' state and return its id."""
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "progress": 0,
            "applicant_id": applicant_id,
            "submitted_at": _now_iso(),
            "document_count": document_count,
            "documents": [],
            "cross_document": [],
            "overall": None,
            "underwriter_decision": None,
            "error": None,
        }
    return job_id


def update(job_id: str, **fields: Any) -> None:
    """Patch fields on an existing job (no-op if the job is gone)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(fields)


def get(job_id: str) -> dict[str, Any] | None:
    """Return a shallow copy of the job state, or None."""
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def all_jobs() -> list[dict[str, Any]]:
    """Return copies of every job (newest first) — used for the history view."""
    with _LOCK:
        jobs = [dict(j) for j in _JOBS.values()]
    jobs.sort(key=lambda j: j.get("submitted_at", ""), reverse=True)
    return jobs
