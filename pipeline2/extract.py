"""
Step 1 of Pipeline 2: VLM/OCR + normalization in a single LLM session.

The model reads the document image(s)/PDF, performs OCR, translates any
regional-language content to English, expands abbreviations, and returns the
fields defined by the document's schema as clean structured JSON.
"""

from __future__ import annotations

from typing import Any

import llm_client
import schemas
import utils

_EXTRACT_SYSTEM = """You are a meticulous document-understanding engine for a bank's
loan-underwriting pipeline.

Your job, in ONE pass over the supplied document image(s)/PDF:
1. OCR: read ALL text, including stamps, seals, handwriting and tables.
2. NORMALIZE: translate any non-English (Hindi, Kannada, Tamil, etc.) labels and
   values into English. Expand abbreviations (e.g. "A.Y." -> assessment_year,
   "Rs." -> currency amount, "S/o" -> son of). Convert dates to YYYY-MM-DD and
   amounts to plain integers/decimals without currency symbols or separators.
3. EXTRACT: populate exactly the requested fields. If a field is absent or
   unreadable, set it to null and list it under "unreadable_fields".

Rules:
- Never guess or fabricate values. Only report what is actually present.
- Preserve names in their printed form (uppercase as printed is fine).
- For Aadhaar, output ONLY the last 4 digits, never the full number.
- IGNORE informational watermarks/disclaimers such as "FOR VIEWING ONLY",
  "NOT FOR LEGAL PURPOSE", "INFORMATIONAL COPY", or e-portal download notices.
  These appear on legitimately downloaded government e-record copies and are NOT
  tampering — do NOT list them under "extraction_observations".
- BE CONCISE so the JSON is never truncated: return ONLY the requested fields.
  Do NOT transcribe full crop/tenancy tables or every row. Keep
  "normalization_notes" and "extraction_observations" to at most 3 SHORT items
  each (or leave them empty) — one brief phrase per item, not paragraphs.
- Return STRICT, COMPACT JSON. No prose, no markdown."""

_CLASSIFY_LINE = (
    "First, classify this document. Choose the single best matching type from "
    "this list (or 'unknown' if none fit): {types}. "
    "Put your choice in the top-level \"doc_type\" field."
)


def _build_user_prompt(schema: dict[str, Any], doc_type: str | None) -> str:
    field_lines = "\n".join(
        f'  - "{name}": {desc}' for name, desc in schema["fields"].items()
    )
    hints = "\n".join(f"  - {h}" for h in schema.get("forgery_hints", []))

    classify = ""
    if doc_type is None:
        classify = _CLASSIFY_LINE.format(types=", ".join(schemas.known_types())) + "\n\n"

    return f"""{classify}Document type (expected): {doc_type or "auto-detect"}

Extract these fields:
{field_lines}

Be alert to these known tampering patterns for this document type (note any you
visibly observe under "extraction_observations", but do NOT score risk here):
{hints or "  - (none listed)"}

Return JSON with this exact shape:
{{
  "doc_type": "<one of the known types or 'unknown'>",
  "fields": {{ <each requested field>: <value or null> }},
  "normalization_notes": [ "<what you translated/expanded>" ],
  "extraction_observations": [ "<any visible anomaly, optional>" ],
  "unreadable_fields": [ "<field names that were unreadable>" ],
  "extraction_confidence": <0.0-1.0>
}}"""


def extract_document(path: str, doc_type: str | None = None) -> dict[str, Any]:
    """
    Read a document and return normalized structured fields.

    Args:
        path: path to an image or PDF.
        doc_type: optional known type. If None, the model classifies it.

    Returns a dict including doc_type, fields, normalization_notes, and the
    schema used (for downstream verification).
    """
    schema = schemas.get_schema(doc_type)
    media = utils.load_media(path)
    user_prompt = _build_user_prompt(schema, doc_type)

    result = llm_client.call_vision(_EXTRACT_SYSTEM, user_prompt, media, json_mode=True)

    # Auto-detect refinement: on the first pass we only had the GENERIC schema's
    # fields (name/title/ids/amounts), so the type-specific KEY fields (e.g. a
    # land record's state/taluka/village/survey_number) were never pulled and the
    # DB lookup can't succeed. If the model identified a known specific type,
    # re-extract with THAT schema's real fields so verification gets proper keys.
    detected = result.get("doc_type")
    if doc_type is None and detected and detected in schemas.SCHEMAS and detected != "unknown":
        schema = schemas.get_schema(detected)
        result = llm_client.call_vision(
            _EXTRACT_SYSTEM, _build_user_prompt(schema, detected), media, json_mode=True
        )
        detected = result.get("doc_type") or detected

    result["_schema"] = {
        "doc_type": detected or doc_type or "unknown",
        "db_collection": schema["db_collection"],
        "key_fields": schema["key_fields"],
        "label": schema["label"],
    }
    result["_source_path"] = path
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
