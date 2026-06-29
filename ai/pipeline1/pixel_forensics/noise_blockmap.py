"""Local noise-energy block scores."""

from __future__ import annotations

import cv2
import numpy as np

from pipeline1.pixel_forensics.block_grid import BlockGrid


def run_noise_anomaly(grid: BlockGrid) -> np.ndarray:
    """Return per-block Laplacian residual variance in grid block order.

    Lower-than-document-normal noise energy is the fraud-relevant direction:
    it can indicate a smoothed, inpainted, or pasted region. Tier 2 applies
    the asymmetric below-median thresholding.
    """

    try:
        grayscale = cv2.cvtColor(grid.working_image, cv2.COLOR_BGR2GRAY)
        residual = cv2.Laplacian(grayscale, cv2.CV_32F)
        scores = []
        for block in grid.blocks:
            crop = residual[block.y : block.y + block.h, block.x : block.x + block.w]
            scores.append(float(np.var(crop)) if crop.size else 0.0)
        return np.asarray(scores, dtype=float)
    except Exception:
        return np.zeros(len(grid.blocks), dtype=float)
