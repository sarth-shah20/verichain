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

from typing import Any

# --------------------------------------------------------------------------- #
# Demo fixture data -- lets the whole pipeline run before the real DB exists.
# Keyed by db_collection (see schemas.py), then by a lookup key.
# Replace / remove once the real backend is wired in.
# --------------------------------------------------------------------------- #
SAMPLE_DB: dict[str, dict[str, dict[str, Any]]] = {
    "itr": {
        "ABCDE1234F|2024-25": {
            "pan": "ABCDE1234F",
            "name": "RAHUL KUMAR SHARMA",
            "assessment_year": "2024-25",
            "gross_total_income": 1180000,
            "total_tax_paid": 138000,
            "employer_name": "ACME TECHNOLOGIES PVT LTD",
            "acknowledgement_number": "1029384756120724",
        }
    },
    "pan": {
        "ABCDE1234F": {
            "pan": "ABCDE1234F",
            "name": "RAHUL KUMAR SHARMA",
            "father_name": "SURESH SHARMA",
            "date_of_birth": "1989-04-12",
        }
    },
    "address_proof": {
        "RAHUL KUMAR SHARMA": {
            "name": "RAHUL KUMAR SHARMA",
            "address": "12, MG Road, Bengaluru 560001",
            "document_basis": "electricity bill",
            "issue_date": "2026-03-10",
        }
    },
}


def _make_lookup_key(key_fields: list[str], values: dict[str, Any]) -> str:
    """Build the composite key used to index SAMPLE_DB (pipe-joined)."""
    parts = [str(values.get(k, "")).strip() for k in key_fields]
    return "|".join(p for p in parts if p)


def _backend_fetch(collection: str, key: str, values: dict[str, Any]) -> dict | None:
    """
    >>> FRIEND: REPLACE THIS BODY WITH THE REAL LOOKUP <<<

    `collection` = db_collection from the schema (e.g. "itr").
    `key`        = composite lookup key built from the document's key fields.
    `values`     = the raw key-field values (use whichever you prefer to query).

    Return the authoritative record dict, or None.
    """
    return SAMPLE_DB.get(collection, {}).get(key)


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
