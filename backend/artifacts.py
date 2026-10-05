"""Forensic heatmap artifact storage.

Heatmap PNGs are written to backend/artifacts/{job_id}/ and served via the
/artifacts static mount. Small binary files stay out of the job JSON and the
SQLite result payload — only URLs + pct boxes travel in the API response.
"""

from __future__ import annotations

import os
from pathlib import Path

_ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


def ensure_dir(job_id: str) -> Path:
    d = _ARTIFACTS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_heatmap(job_id: str, doc_index: int, page_number: int, png_bytes: bytes) -> str:
    """Write one heatmap PNG, return its URL path (mount-relative)."""
    d = ensure_dir(job_id)
    fname = f"doc_{doc_index}_heatmap_p{page_number}.png"
    (d / fname).write_bytes(png_bytes)
    return f"/artifacts/{job_id}/{fname}"


def save_single_heatmap(doc_hash: str, page_number: int, png_bytes: bytes) -> str:
    """Single-doc /verify path (no job id): key by content hash."""
    d = _ARTIFACTS_DIR / "single"
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{doc_hash[:16]}_p{page_number}.png"
    (d / fname).write_bytes(png_bytes)
    return f"/artifacts/single/{fname}"


def artifacts_dir() -> str:
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return str(_ARTIFACTS_DIR)


def prune(job_id: str) -> None:
    """Best-effort cleanup of one job's artifacts (never raises)."""
    try:
        import shutil

        shutil.rmtree(_ARTIFACTS_DIR / job_id, ignore_errors=True)
    except Exception:
        pass
