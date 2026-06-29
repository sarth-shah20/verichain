"""
Central configuration for Pipeline 2 (content extraction + verification).

All LLM access goes through litellm. We target Google Vertex AI.
The model name is read from the environment so it is never hard-coded and can
be swapped without touching application logic.

Required environment variables (Vertex AI):
    LLM_MODEL            e.g. "vertex_ai/<model-id>"   (kept out of source on purpose)
    VERTEXAI_PROJECT     your GCP project id
    VERTEXAI_LOCATION    e.g. "us-central1"
    GOOGLE_APPLICATION_CREDENTIALS  path to the service-account JSON

Optional:
    LLM_MOCK=1           run everything with a deterministic fake LLM (no network)
    LLM_TEMPERATURE      default 0.0 (we want deterministic extraction/verification)
"""

from __future__ import annotations

import os


def get_model() -> str:
    """Return the configured model id (from env). Never hard-code it here."""
    model = os.getenv("LLM_MODEL")
    if not model:
        # Sensible Vertex default if the operator forgot to set it.
        model = "vertex_ai/gemini-pro"
    return model


def get_temperature() -> float:
    try:
        return float(os.getenv("LLM_TEMPERATURE", "0.0"))
    except ValueError:
        return 0.0


def is_mock() -> bool:
    """Mock mode lets the full flow run end-to-end without live Vertex calls."""
    return os.getenv("LLM_MOCK", "").strip() in ("1", "true", "True", "yes")


# Vertex routing is picked up automatically by litellm from these env vars.
VERTEX_PROJECT = os.getenv("VERTEXAI_PROJECT")
VERTEX_LOCATION = os.getenv("VERTEXAI_LOCATION", "us-central1")

# How long (seconds) to wait on a single LLM call before giving up.
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# Max tokens for a response. Verification of records with many fields can be
# long, so keep this generous to avoid truncated JSON.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
