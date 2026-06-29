"""
Mocked database-of-record adapter.

==> THIS IS THE INTEGRATION CONTRACT WITH THE DB TEAMMATE. <==

Pipeline 2 only ever calls `fetch_record(...)`. Your friend implements the body
of `_backend_fetch(...)` (or replaces the in-memory SAMPLE_DB) so that, given a
document type and the key fields extracted from the document, it returns the
authoritative record the bank holds for that entity -- or None if no record.

Return shape (a plain dict):
    {
        "found": True,
        "source": "itr_portal",          # which system of record answered
        "record": { ...authoritative field values... },
        "as_of": "2026-06-01",           # optional freshness stamp
    }
or, when nothing is found:
    {"found": False, "source": None, "record": {}, "as_of": None}

Keep keys in `record` aligned with the field names in schemas.py so verification
can compare like-for-like.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

# Retained for offline/mock mode (LLM_MOCK=1) so demo.py works without a DB.
_MOCK_DB: dict[str, dict[str, dict[str, Any]]] = {
    "itr": {
        "ABKPG7842M|2025-26": {
            "pan": "ABKPG7842M",
            "name": "Mahadev Balu Gadade",
            "assessment_year": "2025-26",
            "gross_total_income": 910000,
            "total_tax_paid": 60000,
            "employer_name": None,
            "acknowledgement_number": "315780214567891",
        }
    },
}

_DB_PATH = os.path.abspath(
    os.environ.get(
        "VERICHAIN_DB",
        os.path.join(os.path.dirname(__file__), "..", "verichain.db"),
    )
)

# Collections that map to the land_records table.
_LAND_COLLECTIONS = {
    "land_record", "karnataka_rtc", "tamilnadu_patta_chitta",
    "maharashtra_712", "land",
}


def _make_lookup_key(key_fields: list[str], values: dict[str, Any]) -> str:
    """Build the pipe-joined composite key used for DB lookups."""
    parts = [str(values.get(k, "")).strip() for k in key_fields]
    return "|".join(p for p in parts if p)


def _backend_fetch(collection: str, key: str, values: dict[str, Any]) -> dict | None:
    """Query verichain.db for the authoritative record.

    Falls back to the in-memory mock when LLM_MOCK=1 or the DB file is absent.
    """
    from config import is_mock  # noqa: PLC0415 — pipeline2 flat-import style

    if is_mock():
        return _MOCK_DB.get(collection, {}).get(key)

    if not os.path.exists(_DB_PATH):
        return None

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        if collection == "itr":
            cur.execute(
                "SELECT pan, name, assessment_year, gross_total_income, "
                "total_tax_paid, employer_name, acknowledgement_number "
                "FROM itr_records WHERE record_key = ?",
                (key,),
            )
        elif collection in _LAND_COLLECTIONS:
            cur.execute(
                "SELECT * FROM land_records WHERE record_key = ?", (key,)
            )
        else:
            return None

        row = cur.fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Public API -- the only thing Pipeline 2 imports.
# --------------------------------------------------------------------------- #
def fetch_record(
    db_collection: str,
    key_fields: list[str],
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Look up the authoritative record for a document.

    Args:
        db_collection: logical record type (schema's db_collection).
        key_fields:    schema's key_fields list.
        extracted_fields: the fields the LLM pulled from the document.

    Returns the standard response dict described in the module docstring.
    """
    key = _make_lookup_key(key_fields, extracted_fields)
    record = _backend_fetch(db_collection, key, extracted_fields)
    if record is None:
        return {"found": False, "source": None, "record": {}, "as_of": None}
    return {
        "found": True,
        "source": db_collection,
        "record": record,
        "as_of": record.get("as_of"),
    }
