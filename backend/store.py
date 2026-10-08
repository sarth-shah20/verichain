"""
Persistent store for completed verifications.

The in-memory job store (jobs.py) holds a batch job only for the process
lifetime. This module persists each completed verification to SQLite so that:
  - the History page survives a server restart / new browser session,
  - a report can be reopened by job_id even after the in-memory job is gone,
  - the underwriter's Approve/Review/Reject decision is recorded.

Delete is SOFT (a `deleted` flag) — the append-only blockchain_log audit trail
is never rewritten, so "immutable audit log" still holds; deleted rows just stop
appearing in the dashboard.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

_DB_PATH = os.path.abspath(
    os.environ.get(
        "VERICHAIN_DB",
        os.path.join(os.path.dirname(__file__), "..", "verichain.db"),
    )
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Create the verifications table and migrate blockchain_log. Idempotent."""
    try:
        with _conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verifications (
                    job_id               TEXT PRIMARY KEY,
                    applicant_id         TEXT,
                    submitted_at         TEXT,
                    doc_names            TEXT,
                    document_count       INTEGER,
                    decision             TEXT,
                    risk_score           INTEGER,
                    underwriter_decision TEXT,
                    result_json          TEXT,
                    deleted              INTEGER DEFAULT 0
                )
                """
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS blockchain_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, applicant_id TEXT, doc_hash TEXT,
                risk_score INTEGER, decision TEXT, timestamp TEXT, tx_hash TEXT,
                event_type TEXT DEFAULT 'system_verdict', note TEXT
            )""")
            # Migrate the existing blockchain_log: add an event_type discriminator
            # so human decisions can be recorded alongside system verdicts without
            # a rebuild. Existing rows default to 'system_verdict'.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(blockchain_log)")}
            if cols and "event_type" not in cols:
                conn.execute(
                    "ALTER TABLE blockchain_log ADD COLUMN event_type TEXT "
                    "DEFAULT 'system_verdict'"
                )
            # Notes: persist underwriter justification for audit.
            vcols = {r[1] for r in conn.execute("PRAGMA table_info(verifications)")}
            if vcols and "note" not in vcols:
                conn.execute("ALTER TABLE verifications ADD COLUMN note TEXT")
            bcols = {r[1] for r in conn.execute("PRAGMA table_info(blockchain_log)")}
            if bcols and "note" not in bcols:
                conn.execute("ALTER TABLE blockchain_log ADD COLUMN note TEXT")
    except sqlite3.Error:
        # Never let store setup crash the app; persistence degrades gracefully.
        pass


def save(job: dict[str, Any]) -> None:
    """Persist a completed batch job (full result) for history + reopen."""
    overall = job.get("overall") or {}
    documents = job.get("documents") or []
    doc_names = ", ".join(d.get("filename", "document") for d in documents)
    payload = {
        "applicant_id": job.get("applicant_id"),
        "submitted_at": job.get("submitted_at"),
        "document_count": job.get("document_count", len(documents)),
        "documents": documents,
        "cross_document": job.get("cross_document", []),
        "overall": overall,
        "underwriter_decision": job.get("underwriter_decision"),
        "analysis_warnings": job.get("analysis_warnings", []),
        "analysis_status": job.get("analysis_status", "complete"),
        "document_stages": job.get("document_stages", []),
        "reconciliation": job.get("reconciliation", []),
        "demo_scenario": job.get("demo_scenario"),
    }
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO verifications
                    (job_id, applicant_id, submitted_at, doc_names, document_count,
                     decision, risk_score, underwriter_decision, result_json, deleted)
                VALUES (?,?,?,?,?,?,?,?,?,
                    COALESCE((SELECT deleted FROM verifications WHERE job_id = ?), 0))
                """,
                (
                    job.get("job_id"),
                    job.get("applicant_id"),
                    job.get("submitted_at"),
                    doc_names,
                    payload["document_count"],
                    overall.get("decision"),
                    overall.get("risk_score"),
                    job.get("underwriter_decision"),
                    json.dumps(payload),
                    job.get("job_id"),
                ),
            )
    except sqlite3.Error:
        pass


def get(job_id: str) -> dict[str, Any] | None:
    """Rebuild a completed job payload from persistence (or None)."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT result_json, underwriter_decision, note FROM verifications "
                "WHERE job_id = ? AND deleted = 0",
                (job_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        payload = json.loads(row["result_json"])
    except (ValueError, TypeError):
        return None
    return {
        "job_id": job_id,
        "status": "done",
        "progress": 100,
        "applicant_id": payload.get("applicant_id"),
        "submitted_at": payload.get("submitted_at"),
        "document_count": payload.get("document_count", 0),
        "documents": payload.get("documents", []),
        "cross_document": payload.get("cross_document", []),
        "overall": payload.get("overall"),
        "underwriter_decision": row["underwriter_decision"],
        "reviewer_note": row["note"],
        "analysis_warnings": payload.get("analysis_warnings", []),
        "analysis_status": payload.get("analysis_status", "legacy"),
        "document_stages": payload.get("document_stages", []),
        "reconciliation": payload.get("reconciliation", []),
        "demo_scenario": payload.get("demo_scenario"),
        "error": None,
    }


def list_all() -> list[dict[str, Any]]:
    """Summary rows for the History page (non-deleted, newest first)."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT job_id, applicant_id, submitted_at, doc_names, document_count, "
                "decision, risk_score, underwriter_decision "
                "FROM verifications WHERE deleted = 0 ORDER BY submitted_at DESC"
            ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def record_decision(job_id: str, decision: str, note: str | None = None) -> dict[str, Any] | None:
    """Save the underwriter's decision + note and append it to the audit log.

    Returns {tx_hash, timestamp} on success, or None if the job isn't persisted.
    """
    if not note or not note.strip():
        raise ValueError("A reviewer note is required.")
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT applicant_id FROM verifications WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return None
            applicant_id = row["applicant_id"]

            conn.execute(
                "UPDATE verifications SET underwriter_decision = ?, note = ? WHERE job_id = ?",
                (decision, note, job_id),
            )

            ts = datetime.now(timezone.utc).isoformat()
            tx_hash = "0x" + hashlib.sha256(
                f"{applicant_id}{job_id}{decision}decision".encode()
            ).hexdigest()[:40]
            # Append as an underwriter_decision event; system verdicts keep the
            # default 'system_verdict' event_type. The audit log is append-only.
            conn.execute(
                "INSERT INTO blockchain_log "
                "(applicant_id, doc_hash, risk_score, decision, timestamp, tx_hash, event_type, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (applicant_id, job_id, None, decision, ts, tx_hash, "underwriter_decision", note),
            )
        return {"tx_hash": tx_hash, "timestamp": ts}
    except sqlite3.Error:
        return None


def soft_delete(job_id: str) -> bool:
    """Hide a verification from the dashboard; the audit log is untouched."""
    try:
        with _conn() as conn:
            cur = conn.execute(
                "UPDATE verifications SET deleted = 1 WHERE job_id = ?", (job_id,)
            )
        return cur.rowcount > 0
    except sqlite3.Error:
        return False
