"""Content filters for browser and print-system artifact text."""

from __future__ import annotations

import re

PRINT_ARTIFACT_PATTERNS = [
    r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}.{0,15}\d{1,2}:\d{2}",
    r"https?://|www\.",
    r"page\s+\d+\s+of\s+\d+",
]


def is_print_artifact_text(text: str) -> bool:
    """Return whether text looks like a browser or print-system artifact."""

    return any(
        re.search(pattern, text, flags=re.IGNORECASE) is not None
        for pattern in PRINT_ARTIFACT_PATTERNS
    )
