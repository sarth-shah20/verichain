"""DCT block-energy anomaly scores."""

from __future__ import annotations

import cv2
import numpy as np
from scipy.fft import dctn

from pipeline1.pixel_forensics.block_grid import BlockGrid


def run_dct_anomaly(grid: BlockGrid) -> np.ndarray:
    """Return per-block AC DCT energy scores in grid block order.

    This signal is weaker/noisier on its own than ELA, and is mainly intended
    to corroborate other signals in the same localized region.
    """

    try:
        grayscale = cv2.cvtColor(grid.working_image, cv2.COLOR_BGR2GRAY)
        scores = []
        for block in grid.blocks:
            crop = grayscale[block.y : block.y + block.h, block.x : block.x + block.w]
            if crop.size == 0:
                scores.append(0.0)
                continue
            coefficients = dctn(crop.astype(np.float32), norm="ortho")
            coefficients[0, 0] = 0.0
            scores.append(float(np.sum(coefficients * coefficients)))
        return np.asarray(scores, dtype=float)
    except Exception:
        return np.zeros(len(grid.blocks), dtype=float)
