"""
Persistent verification history.

    GET    /verifications           -> list past verifications (newest first)
    DELETE /verifications/{job_id}  -> soft-delete one (audit log preserved)

The per-job report itself is reopened via GET /verify/batch/{job_id} (see
batch.py), which falls back to this persistent store when the in-memory job is
gone. The underwriter's decision is recorded via POST /verify/batch/{job_id}/decision.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

import store

router = APIRouter(prefix="/verifications", tags=["history"])


@router.get("")
def list_verifications() -> list[dict[str, Any]]:
    return store.list_all()


@router.delete("/{job_id}")
def delete_verification(job_id: str) -> dict[str, Any]:
    if not store.soft_delete(job_id):
        raise HTTPException(status_code=404, detail="Verification not found.")
    return {"deleted": True, "job_id": job_id}
