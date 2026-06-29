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
    if "MOCK_TASK=extract" in system:
        return json.dumps(
            {
                "doc_type": "salaried_itr",
                "fields": {
                    "pan": "ABCDE1234F",
                    "name": "RAHUL KUMAR SHARMA",
                    "assessment_year": "2024-25",
                    "gross_total_income": 1250000,
                    "total_tax_paid": 145000,
                    "employer_name": "ACME TECHNOLOGIES PVT LTD",
                },
                "normalization_notes": [
                    "Translated regional-language label 'naam' -> 'name'",
                    "Expanded 'A.Y.' -> 'assessment_year'",
                ],
                "extraction_confidence": 0.92,
                "unreadable_fields": [],
            }
        )
    if "MOCK_TASK=verify" in system:
        return json.dumps(
            {
                "match_status": "partial_match",
                "field_results": [
                    {
                        "field": "pan",
                        "document_value": "ABCDE1234F",
                        "database_value": "ABCDE1234F",
                        "match": True,
                        "note": "exact match",
                    },
                    {
                        "field": "gross_total_income",
                        "document_value": 1250000,
                        "database_value": 1180000,
                        "match": False,
                        "note": "Document income higher than filed return by 70,000",
                    },
                ],
                "discrepancies": [
                    {
                        "field": "gross_total_income",
                        "severity": "high",
                        "detail": "Stated income exceeds DB-of-record by 5.9%",
                    }
                ],
                "verification_confidence": 0.88,
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
        return json.dumps(
            {
                "overall_risk_score": 72,
                "risk_band": "high",
                "decision_recommendation": "manual_review",
                "top_flags": [
                    {
                        "source": "verification",
                        "evidence": "ITR income mismatch vs DB-of-record (+5.9%)",
                        "weight": "high",
                    },
                    {
                        "source": "forensics",
                        "evidence": "ELA indicates edited region near income field",
                        "weight": "high",
                    },
                ],
                "rationale": "Independent content and forensic signals both point to the income figure being altered.",
                "false_flag_adjustments": [],
            }
        )
    # default
    return json.dumps({"status": "mock", "echo": "no task marker found"})
