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
import validators

# Deterministic checks whose failure is mathematically definitive (a wrong
# checksum / malformed identifier cannot be a benign OCR variant), so they force
# the overall match_status to "mismatch". The surname-initial check is strong
# evidence but stays advisory (it can be affected by name-extraction quality),
# so it is surfaced as a discrepancy without single-handedly forcing a mismatch.
_DEFINITIVE_CHECKS = {
    "pan_structure", "pan_holder_type",
    "aadhaar_verhoeff",
    "gstin_structure", "gstin_state_code", "gstin_checksum", "gstin_embedded_pan",
}

_VERIFY_SYSTEM = """You are a verification analyst for a bank's loan-underwriting
pipeline.

You are given (A) fields a system extracted from a customer-submitted document and
(B) the authoritative record the bank holds for the same entity. Compare them
field by field and decide whether the document is consistent with the record.

Rules:
- Compare SEMANTICALLY, never by string equality. These documents are OCR'd and
  transliterated from regional scripts (Kannada / Tamil / Marathi / Hindi), so a
  lot of variation is BENIGN noise, NOT fraud. Treat the following as a MATCH
  (note it, but set "match": true and do not raise a discrepancy):
  * Transliteration spelling variants: "Palajangamanalli" ~ "Balajangamanahalli",
    single vs double letters, -halli/-alli endings, b/p, v/w, i/y swaps.
  * Name component order / honorifics: "Ariyakkavundar S/o Kanniyappan" ~
    "Kanniyappan S/o Ariyakavundar" — the SAME two names with father/son order or
    spelling differing.
  * Father-name suffixes present in only one source: "Rajkannu" ~
    "Rajkannu S/o Ganesan" — the SAME person, father's name appended in one only.
  * Co-owners / joint holders (VERY COMMON on land records): a 7/12 · RTC ·
    patta-chitta routinely lists MULTIPLE khatedars, while the DB may store only
    the primary owner (or vice-versa). If the DB's owner appears AMONG the
    document's owner names (allowing the transliteration / order / S/o variance
    above), the entity is CONFIRMED — the extra names are co-holders, NOT fraud.
    Example: document "Krishnappan and Rajkannu" vs DB "Rajkannu S/o Ganesan" is
    a MATCH (Rajkannu is common to both; Krishnappan is a co-owner). Set
    "match": true and do NOT raise a discrepancy.
  * Locality CODE prefixes on a name/village: "014 Balajangamanahalli" ~
    "Balajangamanahalli".
  * Survey/parcel numbers with vs without sub-divisions: "651, 652, 700" ~
    "651/8, 652/1, 652/3, 700/3" — same base survey numbers.
  * Amounts / dates in different formats: "Rs. 12,50,000" == 1250000.
- A matching UNIQUE IDENTIFIER (ULPIN / parcel_id, PAN, account number) CONFIRMS
  this is the correct entity. When it matches, do NOT escalate cosmetic field
  variance — the record is the right one. The same applies when the record was
  located by survey/parcel number: the PARCEL is confirmed, so owner-name
  variance (including additional co-owners) is benign.
- For OWNER / PERSON fields specifically: flag a mismatch ONLY when the DB's
  named person is ENTIRELY ABSENT from the document (a genuine substitution of
  one owner for a different one). Do NOT flag merely because the document lists
  ADDITIONAL names alongside a matching owner, or because a father-name suffix or
  word order differs.
- Flag a real discrepancy (medium/high) ONLY when a value is SUBSTANTIVELY
  different: a genuinely different owner/person (per the rule above), a
  materially different area or monetary amount, or a different survey/parcel
  altogether. For numeric fields, report the absolute and percentage difference
  in the note.
- match_status: "match" if the key fields correspond (allowing the benign variance
  above), "partial_match" for minor unverifiable gaps, "mismatch" ONLY for
  substantive conflicts.
- Do not invent values that were not provided.
- Return STRICT JSON only."""


def _build_user_prompt(
    label: str,
    extracted_fields: dict[str, Any],
    db_response: dict[str, Any],
    full_text: str | None = None,
) -> str:
    full_text_block = ""
    if full_text and full_text.strip():
        full_text_block = f"""(A0) FULL document content (OCR'd + translated to English) — use this as the
primary basis for comparison; it carries context (joint owners, father-name
suffixes, whole tables) that the extracted key fields below may flatten:
\"\"\"
{full_text}
\"\"\"

"""

    return f"""Document type: {label}

{full_text_block}(A) Key fields extracted from the submitted document:
{json.dumps(extracted_fields, indent=2, ensure_ascii=False)}

(B) Authoritative database record:
  found: {db_response.get("found")}
  source: {db_response.get("source")}
  record: {json.dumps(db_response.get("record", {}), indent=2, ensure_ascii=False)}

Compare the document (A0 full content, plus the A key fields) against B. Return
JSON with this exact shape:
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
    doc_type = schema_meta.get("doc_type")
    extracted_fields = extraction.get("fields", {})
    full_text = extraction.get("full_text")

    # Deterministic identifier checks run ALWAYS — they need no DB record, cannot
    # be fooled by an LLM, and catch invented PAN/Aadhaar/GSTIN values even when
    # the entity is outside our DB-of-record scope.
    det_findings = validators.run_validators(doc_type, extracted_fields)

    # Short-circuit: if the bank holds no authoritative record for this entity,
    # there is nothing to compare against. This is NOT fraud -- it is simply
    # outside our verifiable scope. We still attach the deterministic checks so a
    # fabricated identifier is caught regardless of DB coverage.
    if not db_response.get("found"):
        result = _not_in_database_result(label, extracted_fields)
        return _merge_deterministic(result, det_findings)

    result = llm_client.call_text(
        _VERIFY_SYSTEM,
        _build_user_prompt(label, extracted_fields, db_response, full_text),
        json_mode=True,
    )
    result["_db_found"] = True
    result["_verified_at"] = utils.now_iso()
    return _merge_deterministic(result, det_findings)


# Ranking used so deterministic failures can only make match_status WORSE.
_MATCH_RANK = {"match": 0, "unverified": 1, "partial_match": 2, "mismatch": 3}


def _merge_deterministic(
    result: dict[str, Any],
    det_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fold deterministic validator findings into an LLM/no-DB verification result.

    - Every finding is exposed under "deterministic_checks" for transparency.
    - Failures are added as field_results (match=False) and as discrepancies so
      the fusion layer sees them alongside the content comparison.
    - A DEFINITIVE failure (bad checksum / malformed identifier) downgrades
      match_status to "mismatch"; it never upgrades a worse status.
    """
    result["deterministic_checks"] = det_findings
    if not det_findings:
        return result

    field_results = result.setdefault("field_results", [])
    discrepancies = result.setdefault("discrepancies", [])

    definitive_failure = False
    for f in det_findings:
        if f.get("passed") is False:
            field_results.append(
                {
                    "field": f["field"],
                    "document_value": f.get("document_value"),
                    "database_value": f.get("expected"),
                    "match": False,
                    "note": f"[deterministic:{f['check']}] {f['detail']}",
                }
            )
            discrepancies.append(
                {
                    "field": f["field"],
                    "severity": f.get("severity", "high"),
                    "detail": f"[{f['check']}] {f['detail']}",
                }
            )
            if f["check"] in _DEFINITIVE_CHECKS:
                definitive_failure = True

    if definitive_failure:
        current = result.get("match_status", "unverified")
        if _MATCH_RANK.get("mismatch", 3) > _MATCH_RANK.get(current, 1):
            result["match_status"] = "mismatch"
        summary = result.get("summary") or ""
        note = "Deterministic identifier check failed (invalid checksum/structure)."
        result["summary"] = f"{summary} {note}".strip() if summary else note

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
