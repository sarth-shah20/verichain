"""Frequency-domain spectral anomaly block scores."""

from __future__ import annotations

import cv2
import numpy as np
from scipy.fft import fft2, fftshift

from pipeline1.pixel_forensics.block_grid import BlockGrid

MID_FREQ_LOW = 0.12
MID_FREQ_HIGH = 0.35


def run_spectral_anomaly(grid: BlockGrid) -> np.ndarray:
    """Return per-block mid-frequency FFT energy ratios in grid block order."""

    try:
        grayscale = cv2.cvtColor(grid.working_image, cv2.COLOR_BGR2GRAY)
        scores = []
        for block in grid.blocks:
            crop = grayscale[block.y : block.y + block.h, block.x : block.x + block.w]
            if crop.size == 0:
                scores.append(0.0)
                continue

            magnitude = np.abs(fftshift(fft2(crop.astype(np.float32))))
            energy = magnitude * magnitude
            total_energy = float(np.sum(energy))
            if total_energy <= 0.0:
                scores.append(0.0)
                continue

            # This is a frequency-domain annular energy ratio, unlike the Tier 2
            # Laplacian-variance noise map, which is a spatial-domain residual
            # energy measure blended across all frequencies.
            annulus = _mid_frequency_annulus(crop.shape[:2])
            scores.append(float(np.sum(energy[annulus]) / total_energy))
        return np.asarray(scores, dtype=float)
    except Exception:
        return np.zeros(len(grid.blocks), dtype=float)


def _mid_frequency_annulus(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    y_freq = np.fft.fftshift(np.fft.fftfreq(height))
    x_freq = np.fft.fftshift(np.fft.fftfreq(width))
    yy, xx = np.meshgrid(y_freq, x_freq, indexing="ij")
    radius = np.sqrt((yy * yy) + (xx * xx))
    return (radius >= MID_FREQ_LOW) & (radius <= MID_FREQ_HIGH)
