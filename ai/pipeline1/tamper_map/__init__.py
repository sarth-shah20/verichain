"""Tier 3 tamper-map signals for Pipeline 1."""

from pipeline1.tamper_map.spectral import run_spectral_anomaly
from pipeline1.tamper_map.tier3 import run_tier3

__all__ = ["run_spectral_anomaly", "run_tier3"]
