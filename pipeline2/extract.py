"""
Step 1 of Pipeline 2: full-content extraction.

Two passes:
  1. VISION — OCR the whole document, translate any regional script to English,
     and return the COMPLETE document content as `full_text` (tables, co-owners,
     every section — nothing summarised away), plus the document type.
  2. DERIVE — from that English `full_text`, pull the schema's declared fields
     (used as the DB lookup key and by the deterministic identifier validators).

Downstream, verification compares the WHOLE document content against the
authoritative record, not just a handful of essential fields — so context like
joint owners, father-name suffixes and full tables is preserved and benign
variance stops being misread as a mismatch.
"""

from __future__ import annotations

from typing import Any

import llm_client
import schemas
import utils

# --------------------------------------------------------------------------- #
# Pass 1: full-content OCR + translation
# --------------------------------------------------------------------------- #
_FULLTEXT_SYSTEM = """You are a meticulous document-understanding engine for a
bank's loan-underwriting pipeline.

In ONE pass over the supplied document image(s)/PDF:
1. OCR: read ALL text — headings, stamps, seals, handwriting, and EVERY table
   row (crop/tenancy tables, transaction lines, co-owner lists, etc.).
2. TRANSLATE: render any non-English content (Hindi, Kannada, Tamil, Marathi,
   etc.) into English. Expand abbreviations ("A.Y." -> assessment year, "S/o" ->
   son of). Keep names in their printed form.
3. RETURN the COMPLETE content as a single English string in "full_text". Do NOT
   summarise, omit rows, or drop sections — preserve the whole document,
   including every owner/khatedar name and every table line, in reading order.
   Mark page boundaries as [Page 1], [Page 2], etc. Preserve every bank debit,
   credit, running balance and transaction date, including blank opposite columns.
4. CLASSIFY the document type.

Rules:
- Never fabricate. Transcribe only what is present.
- IGNORE informational watermarks/disclaimers ("FOR VIEWING ONLY", "NOT FOR
  LEGAL PURPOSE", "INFORMATIONAL COPY", e-portal download notices) — these are
  normal on downloaded government e-records and are NOT tampering.
- Return STRICT JSON. No markdown, no prose outside the JSON."""

_CLASSIFY_LINE = (
    "Classify this document as the single best matching type from this list "
    "(or 'unknown' if none fit): {types}."
)


def _build_fulltext_prompt(doc_type: str | None) -> str:
    if doc_type is None:
        classify = _CLASSIFY_LINE.format(types=", ".join(schemas.known_types()))
    else:
        classify = f"Expected document type: {doc_type}."
    return f"""{classify}

Read the ENTIRE document and return JSON with this exact shape:
{{
  "doc_type": "<one of the known types or 'unknown'>",
  "language": "<primary language of the source document, e.g. English, Tamil>",
  "full_text": "<the COMPLETE document content, OCR'd and translated to English, preserving every section, table row and owner name>"
}}"""


# --------------------------------------------------------------------------- #
# Pass 2: derive the schema's declared fields from the English full_text
# --------------------------------------------------------------------------- #
_DERIVE_SYSTEM = """You extract structured fields from a document's already-OCR'd,
English text for a bank pipeline.

Rules:
- Use ONLY the provided text. Never guess or fabricate; if a field is absent, set
  it to null and list its name under "unreadable_fields".
- Convert dates to YYYY-MM-DD and amounts to plain numbers (no currency symbols
  or thousands separators).
- For Aadhaar: "aadhaar_number" is the FULL 12-digit number (digits only) and
  "aadhaar_last4" is its last four digits.
- If a field has several values in the document (e.g. multiple owners), return
  them all, comma-separated, in reading order.
- Return STRICT JSON only."""


def _build_derive_prompt(schema: dict[str, Any], full_text: str) -> str:
    field_lines = "\n".join(
        f'  - "{name}": {desc}' for name, desc in schema["fields"].items()
    )
    return f"""Document type: {schema.get("label", "Document")}

Full document content (English):
\"\"\"
{full_text}
\"\"\"

Extract these fields from the text above:
{field_lines}

Return JSON with this exact shape:
{{
  "fields": {{ <each requested field>: <value or null> }},
  "unreadable_fields": [ "<field names not found in the text>" ],
  "extraction_confidence": <0.0-1.0>
}}"""


# --------------------------------------------------------------------------- #
# Coercion helpers (models sometimes return arrays / flat keys)
# --------------------------------------------------------------------------- #
def _coerce_fulltext(result: Any) -> dict[str, Any]:
    """Normalize the pass-1 response into {doc_type, language, full_text}."""
    if isinstance(result, list):
        result = next((x for x in result if isinstance(x, dict)), {})
    if not isinstance(result, dict):
        result = {}
    full_text = result.get("full_text")
    if isinstance(full_text, list):
        full_text = "\n".join(str(x) for x in full_text)
    if not isinstance(full_text, str):
        full_text = "" if full_text is None else str(full_text)
    return {
        "doc_type": result.get("doc_type"),
        "language": result.get("language"),
        "full_text": full_text,
    }


def _coerce_fields(result: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize the pass-2 response into a dict with a "fields" dict.

    Handles a top-level array, a fields-as-list-of-fragments, and the model
    emitting the schema fields flat at the top level.
    """
    if isinstance(result, list):
        result = next((x for x in result if isinstance(x, dict)), {})
    if not isinstance(result, dict):
        result = {}

    fields = result.get("fields")
    if isinstance(fields, list):
        merged: dict[str, Any] = {}
        for item in fields:
            if isinstance(item, dict):
                merged.update(item)
        fields = merged
    if not isinstance(fields, dict):
        fields = {}

    if not fields:  # model put fields flat at the top level
        schema_field_names = set(schema.get("fields", {}).keys())
        salvaged = {
            k: v for k, v in result.items()
            if k in schema_field_names and not k.startswith("_")
        }
        if salvaged:
            fields = salvaged

    result["fields"] = fields
    return result


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def extract_document(path: str, doc_type: str | None = None) -> dict[str, Any]:
    """
    Read a document → full English content → derived schema fields.

    Args:
        path: path to an image or PDF.
        doc_type: optional known type. If None, the model classifies it.

    Returns a dict with doc_type, language, full_text, fields, and the schema
    used (for downstream DB lookup + verification).
    """
    # Pass 1 — full content + classification (no length cap; preserve everything).
    with utils.document_media(path) as media:
        fulltext = _coerce_fulltext(
            llm_client.call_vision(
                _FULLTEXT_SYSTEM, _build_fulltext_prompt(doc_type), media, json_mode=True
            )
        )
    detected = fulltext.get("doc_type")
    resolved_type = (
        detected if (doc_type is None and detected in schemas.SCHEMAS and detected != "unknown")
        else doc_type
    )
    schema = schemas.get_schema(resolved_type)
    full_text = fulltext["full_text"]

    # Pass 2 — derive the schema's declared fields FROM the full English text.
    # Runs as a text call (cheaper, and judges the content the pipeline will
    # actually compare). Skipped only if pass 1 recovered no text at all.
    if full_text.strip():
        derived = _coerce_fields(
            llm_client.call_text(
                _DERIVE_SYSTEM, _build_derive_prompt(schema, full_text), json_mode=True
            ),
            schema,
        )
    else:
        derived = {"fields": {}, "unreadable_fields": list(schema["fields"].keys())}

    result: dict[str, Any] = {
        "doc_type": resolved_type or detected or "unknown",
        "language": fulltext.get("language"),
        "full_text": full_text,
        "fields": derived.get("fields", {}),
        "unreadable_fields": derived.get("unreadable_fields", []),
        "extraction_confidence": derived.get("extraction_confidence"),
        "normalization_notes": [],
        "extraction_observations": [],
    }
    bank_warnings = []
    if result["doc_type"] == "bank_statement":
        from bank_reconciliation import normalize_statement
        result["fields"], bank_warnings = normalize_statement(result["fields"])
    result["_schema"] = {
        "doc_type": result["doc_type"],
        "db_collection": schema["db_collection"],
        "key_fields": schema["key_fields"],
        "label": schema["label"],
    }
    result["_source_path"] = path
    required = schema.get("key_fields", [])
    warnings = list(bank_warnings)
    if not full_text.strip():
        warnings.append("No readable document text was recovered.")
    missing = [k for k in required if result["fields"].get(k) in (None, "")]
    if missing:
        warnings.append("Missing lookup fields: " + ", ".join(missing))
    result["analysis_warnings"] = warnings
    result["_extracted_at"] = utils.now_iso()
    return result


if __name__ == "__main__":
    import json
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else None
    dt = sys.argv[2] if len(sys.argv) > 2 else None
    if not p:
        print("usage: python extract.py <file> [doc_type]")
        raise SystemExit(1)
    print(json.dumps(extract_document(p, dt), indent=2, ensure_ascii=False))
