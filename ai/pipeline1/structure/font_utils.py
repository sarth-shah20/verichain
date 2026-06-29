"""Helpers for comparing PDF font families without style false positives."""

from __future__ import annotations

import re

STYLE_TOKENS = (
    "extrabold",
    "semibold",
    "condensed",
    "regular",
    "oblique",
    "medium",
    "italic",
    "narrow",
    "roman",
    "light",
    "heavy",
    "bold",
    "black",
    "thin",
    "mt",
    "ps",
)
SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
TIMES_NEW_ROMAN_PLACEHOLDER = "__tnrfamily__"


def normalize_font_family(font_name: str) -> str:
    """Return a style-insensitive normalized PDF font family name."""

    normalized = _compact_font_name(font_name)
    normalized = normalized.replace("timesnewroman", TIMES_NEW_ROMAN_PLACEHOLDER)
    for token in STYLE_TOKENS:
        normalized = normalized.replace(token, "")
    return normalized.replace(TIMES_NEW_ROMAN_PLACEHOLDER, "timesnewroman")


def font_style_tokens(font_name: str) -> set[str]:
    """Return style/weight tokens present in a prefix-stripped font name."""

    compact_name = _compact_font_name(font_name)
    return {token for token in STYLE_TOKENS if token in compact_name}


def _compact_font_name(font_name: str) -> str:
    without_prefix = SUBSET_PREFIX_RE.sub("", font_name)
    lowered = without_prefix.lower()
    return re.sub(r"[-+, ]", "", lowered)
