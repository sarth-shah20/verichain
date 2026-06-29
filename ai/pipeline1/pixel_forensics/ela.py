"""Error Level Analysis block scores."""

from __future__ import annotations

import cv2
import numpy as np

from pipeline1.pixel_forensics.block_grid import BlockGrid

JPEG_QUALITY = 90


def run_ela(grid: BlockGrid) -> dict[str, list[float]]:
    """Return per-block mean ELA intensity in grid block order."""

    image = grid.working_image
    try:
        ok, encoded = cv2.imencode(
            ".jpg",
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        if not ok:
            return {"block_scores": [0.0 for _ in grid.blocks]}
        recompressed = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if recompressed is None:
            return {"block_scores": [0.0 for _ in grid.blocks]}
        diff = cv2.absdiff(image, recompressed)
        intensity = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        return {"block_scores": _block_means(grid, intensity)}
    except Exception:
        return {"block_scores": [0.0 for _ in grid.blocks]}


def _block_means(grid: BlockGrid, image: np.ndarray) -> list[float]:
    scores = []
    for block in grid.blocks:
        crop = image[block.y : block.y + block.h, block.x : block.x + block.w]
        scores.append(float(np.mean(crop)) if crop.size else 0.0)
    return scores
