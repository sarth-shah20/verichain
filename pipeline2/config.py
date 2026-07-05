"""
Central configuration for Pipeline 2 (content extraction + verification).

All model access goes through a single client wrapper. The model id and any
provider credentials are read from the environment so they are never hard-coded
and the underlying provider can be swapped without touching application logic.

Required environment variable:
    LLM_MODEL            the model id to use (kept out of source on purpose)

Optional:
    LLM_TEMPERATURE      default 0.0 (we want deterministic extraction/verification)
    LLM_TIMEOUT          per-call timeout in seconds (default 120)
    LLM_MAX_TOKENS       max response tokens (default 8192)

Any additional provider credentials are picked up automatically from the
environment by the client wrapper; they are intentionally not referenced here.
"""

from __future__ import annotations

import os


def get_model() -> str:
    """Return the configured model id (from env). Never hard-code it here."""
    model = os.getenv("LLM_MODEL")
    if not model:
        raise RuntimeError(
            "LLM_MODEL is not set. Configure the model id in the environment "
            "before running the pipeline."
        )
    return model


def get_temperature() -> float:
    try:
        return float(os.getenv("LLM_TEMPERATURE", "0.0"))
    except ValueError:
        return 0.0


# How long (seconds) to wait on a single model call before giving up.
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# Max tokens for a response. Extraction now returns the FULL document content
# (full_text) and verification echoes field-by-field over the whole document, so
# responses are larger — keep this generous to avoid truncated JSON.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16384"))
