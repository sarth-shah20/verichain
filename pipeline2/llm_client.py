"""
Thin wrapper around litellm so the rest of the codebase never imports litellm
directly. This gives us one place for:
  - Vertex AI routing
  - JSON-mode prompting + robust JSON parsing
  - multimodal (image / PDF page) message construction
  - a deterministic MOCK mode for offline demos / CI

Public API:
    call_text(system, user, *, json_mode=True) -> dict | str
    call_vision(system, user_text, media: list[Media], *, json_mode=True) -> dict | str
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import Any

import config


@dataclass
class Media:
    """A single image or PDF (already on disk) to send to the vision model."""
    path: str

    @property
    def mime(self) -> str:
        guessed, _ = mimetypes.guess_type(self.path)
        if guessed:
            return guessed
        # default to png if unknown image, pdf handled by extension
        if self.path.lower().endswith(".pdf"):
            return "application/pdf"
        return "image/png"

    def to_data_url(self) -> str:
        with open(self.path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("utf-8")
        return f"data:{self.mime};base64,{b64}"


# --------------------------------------------------------------------------- #
# JSON parsing helpers
# --------------------------------------------------------------------------- #
def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # remove ```json ... ``` or ``` ... ```
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def parse_json(text: str) -> Any:
    """Best-effort JSON extraction from an LLM response."""
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back: grab the first {...} or [...] block.
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Last resort: the response was likely truncated (token limit). Try to
    # repair it by trimming the dangling tail and closing open brackets.
    repaired = _repair_truncated_json(cleaned)
    if repaired is not None:
        return repaired
    raise ValueError(f"Could not parse JSON from model output:\n{text[:500]}")


def _repair_truncated_json(text: str):
    """
    Best-effort recovery of a JSON object/array that was cut off mid-output.
    Walks the string tracking brackets/strings, drops anything after the last
    complete element, and appends the closing brackets. Returns parsed JSON or
    None if it still can't be salvaged.
    """
    start = next((i for i, c in enumerate(text) if c in "{["), None)
    if start is None:
        return None

    stack: list[str] = []
    in_str = False
    escape = False
    last_safe = None  # index just after a completed value (',' or close bracket)

    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
                last_safe = i + 1
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
            last_safe = i + 1
        elif c in ",":
            last_safe = i  # cut BEFORE the comma to drop the partial next item
        elif c.isdigit() or c in "}].truefalsen":
            last_safe = i + 1

    if last_safe is None:
        return None

    candidate = text[start:last_safe].rstrip().rstrip(",")
    # Re-close any still-open brackets (innermost first).
    # Recompute remaining open brackets for the trimmed candidate.
    stack = []
    in_str = False
    escape = False
    for c in candidate:
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]" and stack:
            stack.pop()
    candidate += "".join(reversed(stack))

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Core call
# --------------------------------------------------------------------------- #
def _messages(system: str, content: Any) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def _invoke(messages: list[dict], json_mode: bool) -> str:
    if config.is_mock():
        return _mock_response(messages)

    # Imported lazily so mock mode / tests don't require litellm installed.
    import litellm  # noqa: WPS433

    kwargs: dict[str, Any] = {
        "model": config.get_model(),
        "messages": messages,
        "temperature": config.get_temperature(),
        "max_tokens": config.LLM_MAX_TOKENS,
        "timeout": config.LLM_TIMEOUT,
    }
    if config.VERTEX_PROJECT:
        kwargs["vertex_project"] = config.VERTEX_PROJECT
        kwargs["vertex_location"] = config.VERTEX_LOCATION
    if json_mode:
        # Vertex/Gemini honour this; harmless elsewhere.
        kwargs["response_format"] = {"type": "json_object"}

    resp = litellm.completion(**kwargs)
    return resp["choices"][0]["message"]["content"]


def call_text(system: str, user: str, *, json_mode: bool = True):
    raw = _invoke(_messages(system, user), json_mode)
    return parse_json(raw) if json_mode else raw


def call_vision(
    system: str,
    user_text: str,
    media: list[Media],
    *,
    json_mode: bool = True,
):
    content: list[dict] = [{"type": "text", "text": user_text}]
    for m in media:
        content.append(
            {"type": "image_url", "image_url": {"url": m.to_data_url()}}
        )
    raw = _invoke(_messages(system, content), json_mode)
    return parse_json(raw) if json_mode else raw


# --------------------------------------------------------------------------- #
# Mock backend (deterministic, offline) -- only used when LLM_MOCK=1
# --------------------------------------------------------------------------- #
def _mock_response(messages: list[dict]) -> str:
    """
    Returns canned, schema-shaped JSON so the whole pipeline can be exercised
    without Vertex. It keys off marker strings placed in the system prompt by
    each module.
    """
    system = messages[0]["content"]

    # Extract user message text (handles both plain string and vision list).
    raw_user = messages[1]["content"] if len(messages) > 1 else ""
    if isinstance(raw_user, list):
        user_text = " ".join(
            m.get("text", "") for m in raw_user if isinstance(m, dict)
        )
    else:
        user_text = raw_user

    if "MOCK_TASK=extract" in system:
        # Return the one ITR we have in verichain.db so the DB lookup succeeds.
        return json.dumps(
            {
                "doc_type": "salaried_itr",
                "fields": {
                    "pan": "ABKPG7842M",
                    "name": "Mahadev Balu Gadade",
                    "assessment_year": "2025-26",
                    "gross_total_income": 910000,
                    "total_tax_paid": 60000,
                    "employer_name": None,
                    "acknowledgement_number": "315780214567891",
                },
                "normalization_notes": [],
                "extraction_confidence": 0.90,
                "unreadable_fields": [],
            }
        )
    if "MOCK_TASK=verify" in system:
        # In mock mode we return a clean "match" — the DB holds the correct data
        # for ABKPG7842M so extracted vs. DB values agree.
        # Genuine mismatch testing requires real LLM calls.
        return json.dumps(
            {
                "match_status": "match",
                "db_record_present": True,
                "field_results": [
                    {
                        "field": "pan",
                        "document_value": "ABKPG7842M",
                        "database_value": "ABKPG7842M",
                        "match": True,
                        "note": "exact match",
                    },
                    {
                        "field": "gross_total_income",
                        "document_value": 910000,
                        "database_value": 910000,
                        "match": True,
                        "note": "exact match",
                    },
                    {
                        "field": "assessment_year",
                        "document_value": "2025-26",
                        "database_value": "2025-26",
                        "match": True,
                        "note": "exact match",
                    },
                ],
                "discrepancies": [],
                "verification_confidence": 0.92,
                "summary": "All key fields match the authoritative record.",
            }
        )
    if "MOCK_TASK=cross_doc" in system:
        return json.dumps(
            {
                "entity_consistency": "inconsistent",
                "discrepancies": [
                    {
                        "attribute": "address",
                        "documents": ["payslip", "address_proof"],
                        "values": ["MG Road, Bengaluru", "Whitefield, Bengaluru"],
                        "severity": "medium",
                        "detail": "Address differs across two submitted documents",
                    }
                ],
                "consistent_attributes": ["name", "pan"],
                "summary": "Name and PAN agree across documents; residential address conflicts.",
            }
        )
    if "MOCK_TASK=fusion" in system:
        # Score based on verification match_status present in the user prompt.
        # Fusion LLM uses 0=clean, 100=fraud; verify.py inverts to authenticity score.
        if '"match_status": "match"' in user_text or '"match_status":"match"' in user_text:
            risk_score, band, rec = 5, "low", "approve"
            flags = [{"source": "verification", "evidence": "All fields match DB-of-record", "weight": "low"}]
            rationale = "Content verification found no discrepancies; forensics show no manipulation signals."
        elif '"match_status": "mismatch"' in user_text or '"match_status":"mismatch"' in user_text:
            risk_score, band, rec = 82, "high", "decline"
            flags = [
                {"source": "verification", "evidence": "Critical field mismatch vs DB-of-record", "weight": "high"},
                {"source": "forensics", "evidence": "Pixel-level anomaly near modified field", "weight": "high"},
            ]
            rationale = "Income figure differs significantly from authoritative record; forensic signals corroborate the edit."
        else:
            # unverified / partial_match / no record found → human review
            risk_score, band, rec = 28, "low", "manual_review"
            flags = [{"source": "verification", "evidence": "Document could not be fully verified against DB", "weight": "medium"}]
            rationale = "No matching authoritative record; document authenticity cannot be confirmed without human review."
        return json.dumps(
            {
                "overall_risk_score": risk_score,
                "risk_band": band,
                "decision_recommendation": rec,
                "top_flags": flags,
                "corroborated_findings": [],
                "false_flag_adjustments": [],
                "rationale": rationale,
            }
        )
    # default
    return json.dumps({"status": "mock", "echo": "no task marker found"})
