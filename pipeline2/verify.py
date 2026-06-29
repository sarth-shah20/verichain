"""
Step 2 of Pipeline 2: verification in a SEPARATE LLM session.

This deliberately runs as a fresh session (no extraction context carried over)
so the model judges the comparison on the data alone. It compares the fields
extracted from the document against the authoritative record fetched from the
database-of-record and reports field-level matches and discrepancies.
"""

from __future__ import annotations

import json
from typing import Any

import llm_client
import utils

_VERIFY_SYSTEM = """You are a verification analyst for a bank's loan-underwriting
pipeline. MOCK_TASK=verify

You are given (A) fields a system extracted from a customer-submitted document and
(B) the authoritative record the bank holds for the same entity. Compare them
field by field and decide whether the document is consistent with the record.

Rules:
- Compare semantically, not just by string equality: "Rs. 12,50,000" == 1250000,
  "RAHUL K SHARMA" ~ "Rahul Kumar Sharma" (note as a soft/partial match).
- For numeric fields, report the absolute and percentage difference in the note.
- A record EXISTS for this entity (it was provided). So when values disagree,
  this is a real, serious discrepancy -- flag it firmly (medium/high), because
  the data could not be matched to what the bank already holds.
- Rate each real discrepancy severity: low / medium / high.
- Do not invent values that were not provided.
- Return STRICT JSON only."""


def _build_user_prompt(
    label: str,
    extracted_fields: dict[str, Any],
    db_response: dict[str, Any],
) -> str:
    return f"""Document type: {label}

(A) Fields extracted from the submitted document:
{json.dumps(extracted_fields, indent=2, ensure_ascii=False)}

(B) Authoritative database record:
  found: {db_response.get("found")}
  source: {db_response.get("source")}
  record: {json.dumps(db_response.get("record", {}), indent=2, ensure_ascii=False)}

Compare A vs B. Return JSON with this exact shape:
{{
  "match_status": "match" | "partial_match" | "mismatch",
  "db_record_present": true,
  "field_results": [
    {{
      "field": "<name>",
      "document_value": <value>,
      "database_value": <value or null>,
      "match": true|false,
      "note": "<short explanation, include numeric diffs>"
    }}
  ],
  "discrepancies": [
    {{ "field": "<name>", "severity": "low|medium|high", "detail": "<why it matters>" }}
  ],
  "verification_confidence": <0.0-1.0>,
  "summary": "<one-line plain-English verdict>"
}}"""


def verify_document(extraction: dict[str, Any], db_response: dict[str, Any]) -> dict[str, Any]:
    """
    Compare extracted fields against the DB record.

    Args:
        extraction: output of extract.extract_document (has "fields" + "_schema").
        db_response: output of db.fetch_record.
    """
    schema_meta = extraction.get("_schema", {})
    label = schema_meta.get("label", "Document")
    extracted_fields = extraction.get("fields", {})

    # Short-circuit: if the bank holds no authoritative record for this entity,
    # there is nothing to compare against. This is NOT fraud -- it is simply
    # outside our verifiable scope. We return a deterministic "unverified"
    # result (no LLM call) so such documents are flagged softly, not harshly.
    if not db_response.get("found"):
        return _not_in_database_result(label, extracted_fields)

    result = llm_client.call_text(
        _VERIFY_SYSTEM,
        _build_user_prompt(label, extracted_fields, db_response),
        json_mode=True,
    )
    result["_db_found"] = True
    result["_verified_at"] = utils.now_iso()
    return result


def _not_in_database_result(label: str, extracted_fields: dict[str, Any]) -> dict[str, Any]:
    """Deterministic verdict for documents with no matching DB record."""
    return {
        "match_status": "unverified",
        "db_record_present": False,
        "field_results": [
            {
                "field": name,
                "document_value": value,
                "database_value": None,
                "match": None,
                "note": "No authoritative record on file to compare against.",
            }
            for name, value in extracted_fields.items()
        ],
        # Intentionally empty: absence of a record is not a discrepancy.
        "discrepancies": [],
        "verification_confidence": None,
        "summary": (
            f"{label} could not be verified -- no matching record in the "
            f"bank's database of record. Treat as unverified (not a forgery "
            f"signal on its own); rely on forensics / cross-document checks."
        ),
        "_db_found": False,
        "_verified_at": utils.now_iso(),
    }
