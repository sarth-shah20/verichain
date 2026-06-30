"""
Thin model-client wrapper so the rest of the codebase has a single place for:
  - model invocation (provider configured entirely via the environment)
  - JSON-mode prompting + robust JSON parsing
  - multimodal (image / PDF page) message construction

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
    Best-effort recovery of a JSON object/array cut off mid-output.

    We scan once and record every safe boundary — the index right after each
    completed string and each closed bracket, with the still-open bracket stack
    at that point. Then we try those boundaries longest-first: trim there,
    re-close the open brackets, and attempt to parse; the first that parses wins.
    This avoids the classic bug of cutting right after a dangling KEY (e.g.
    `..., "normalization_notes"` with no value), which a naive "last safe index"
    walk produces and which then fails to parse.

    Returns parsed JSON or None if nothing is salvageable.
    """
    start = next((i for i, c in enumerate(text) if c in "{["), None)
    if start is None:
        return None

    s = text[start:]
    in_str = False
    escape = False
    stack: list[str] = []
    boundaries: list[tuple[int, list[str]]] = []  # (end-in-s, open-stack-there)

    for i, c in enumerate(s):
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
                boundaries.append((i + 1, list(stack)))
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
            boundaries.append((i + 1, list(stack)))

    for end, open_stack in reversed(boundaries):
        candidate = s[:end].rstrip().rstrip(",")
        candidate += "".join(reversed(open_stack))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
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
    import litellm  # imported lazily so import-time has no hard dependency

    kwargs: dict[str, Any] = {
        "model": config.get_model(),
        "messages": messages,
        "temperature": config.get_temperature(),
        "max_tokens": config.LLM_MAX_TOKENS,
        "timeout": config.LLM_TIMEOUT,
    }
    if json_mode:
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
