"""Tier 0 provenance checks for Pipeline 1."""

from __future__ import annotations

from pathlib import Path

from pipeline1.classifier import classify
from pipeline1.schema import TierResult

from .mock_registry import (
    RegistryRecord,
    lookup_by_hash,
    lookup_by_qr_payload,
    register,
    sha256_of_file,
)
from .qr import find_qr_codes
from .signature import check_signature
from .tier0 import run_tier0


def run_provenance(path: str | Path) -> TierResult:
    """Compatibility wrapper that classifies before running Tier 0."""

    return run_tier0(path, classify(path))


__all__ = [
    "RegistryRecord",
    "check_signature",
    "find_qr_codes",
    "lookup_by_hash",
    "lookup_by_qr_payload",
    "register",
    "run_provenance",
    "run_tier0",
    "sha256_of_file",
]
