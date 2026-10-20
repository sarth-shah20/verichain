"""JPEG ghost / double-compression anomaly scores.

A locally edited region re-saved inside a JPEG often carries a different
quantization history than the rest of the image. Re-compressing at several
qualities and taking the per-block minimum difference highlights regions
whose compression response diverges from the document norm — the classic
"JPEG ghost" signal. Global recompression (benign re-save) shifts all blocks
together and is suppressed by the median/MAD outlier step in tier2.
"""

from __future__ import annotations

import cv2
import numpy as np

from pipeline1.pixel_forensics.block_grid import BlockGrid

# Sweep qualities: cheap (3 encodes) but covers low/mid/high re-save histories.
GHOST_QUALITIES = (60, 75, 90)


def run_jpeg_ghost(grid: BlockGrid) -> np.ndarray:
    """Return per-block ghost scores (min over qualities) in block order."""
    try:
        image = grid.working_image
        if image is None or image.size == 0:
            return np.zeros(len(grid.blocks), dtype=float)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        per_q: list[np.ndarray] = []
        for q in GHOST_QUALITIES:
            ok, enc = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if not ok:
                continue
            recomp = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE)
            if recomp is None or recomp.shape != gray.shape:
                continue
            diff = np.abs(gray - recomp.astype(np.float32))
            per_q.append(_block_means(grid, diff))
        if not per_q:
            return np.zeros(len(grid.blocks), dtype=float)
        stacked = np.stack(per_q, axis=0)
        return np.min(stacked, axis=0).astype(float)
    except Exception:
        return np.zeros(len(grid.blocks), dtype=float)


def _block_means(grid: BlockGrid, image: np.ndarray) -> np.ndarray:
    scores = []
    for block in grid.blocks:
        crop = image[block.y : block.y + block.h, block.x : block.x + block.w]
        scores.append(float(np.mean(crop)) if crop.size else 0.0)
    return np.asarray(scores, dtype=float)
