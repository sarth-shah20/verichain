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
import re
import sqlite3
from typing import Any

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


def _norm(v: Any) -> str:
    return str(v if v is not None else "").strip().lower()


def _survey_bases(value: Any) -> set[str]:
    """Base survey number(s), ignoring hissa/sub-divisions.

    Extraction and the DB disagree on sub-numbers (e.g. extracted "115/2" vs
    stored "115", or "651/8, 652/1" vs "651, 652, 700"), so we compare on the
    leading number of each comma-separated token only.
    """
    bases: set[str] = set()
    for token in re.split(r"[,;]", _norm(value)):
        m = re.match(r"\s*(\d+)", token)  # leading digits, drops "/2" etc.
        if m:
            bases.add(m.group(1))
    return bases


def _fetch_land(cur: sqlite3.Cursor, values: dict[str, Any]) -> dict | None:
    """Tolerant land-record lookup.

    LLM-extracted locality fields rarely reproduce a composite key
    (state|district|taluka|village|survey_number) character-for-character, so we
    match on the stable survey/parcel identifier and disambiguate by locality +
    owner overlap instead of an exact key string.
    """
    parcel = _norm(values.get("parcel_id")).replace(" ", "")
    survey_bases = _survey_bases(values.get("survey_number"))

    # 1. Exact parcel/Bhoomi/ULPIN id is the strongest signal (ignore spacing).
    if parcel:
        cur.execute(
            "SELECT * FROM land_records WHERE replace(lower(parcel_id),' ','') = ?",
            (parcel,),
        )
        row = cur.fetchone()
        if row:
            return dict(row)

    if not survey_bases:
        return None

    # 2. Candidates sharing a base survey number, disambiguated by locality/owner.
    cur.execute("SELECT * FROM land_records")
    candidates = [
        r for r in (dict(x) for x in cur.fetchall())
        if _survey_bases(r.get("survey_number")) & survey_bases
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def overlap(rec: dict) -> int:
        score = 0
        for field in ("village", "taluka", "district", "state", "owner_name"):
            tgt, got = _norm(values.get(field)), _norm(rec.get(field))
            if tgt and got and (tgt in got or got in tgt):
                score += 1
        return score

    best = max(candidates, key=overlap)
    return best if overlap(best) > 0 else candidates[0]


def _backend_fetch(collection: str, key: str, values: dict[str, Any]) -> dict | None:
    """Query verichain.db for the authoritative record."""
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
            return _fetch_land(cur, values)
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
