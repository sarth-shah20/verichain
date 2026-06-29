"""Shared block grid and robust outlier helpers for pixel forensics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np
from scipy import ndimage

MAX_WORKING_DIM = 1600
BLOCK_SIZE = 32
MAD_EPSILON = 1e-6


@dataclass(frozen=True)
class Block:
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int


@dataclass
class BlockGrid:
    working_image: np.ndarray
    scale_to_original: float
    blocks: list[Block]
    rows: int
    cols: int
    original_shape: tuple[int, int]

    def block_bbox_original(self, block: Block) -> tuple[int, int, int, int]:
        return _scale_bbox_to_original(
            (block.x, block.y, block.w, block.h),
            self.scale_to_original,
            self.original_shape,
        )


def make_grid(image: np.ndarray) -> BlockGrid:
    """Build a regular block grid over a possibly downscaled working image."""

    original_height, original_width = image.shape[:2]
    longest_side = max(original_width, original_height)
    if longest_side > MAX_WORKING_DIM:
        working_scale = MAX_WORKING_DIM / float(longest_side)
        working_width = max(1, int(round(original_width * working_scale)))
        working_height = max(1, int(round(original_height * working_scale)))
        working_image = cv2.resize(
            image,
            (working_width, working_height),
            interpolation=cv2.INTER_AREA,
        )
        scale_to_original = 1.0 / working_scale
    else:
        working_image = image.copy()
        scale_to_original = 1.0

    working_height, working_width = working_image.shape[:2]
    rows = int(np.ceil(working_height / BLOCK_SIZE))
    cols = int(np.ceil(working_width / BLOCK_SIZE))
    blocks = []
    for row in range(rows):
        y = row * BLOCK_SIZE
        h = min(BLOCK_SIZE, working_height - y)
        for col in range(cols):
            x = col * BLOCK_SIZE
            w = min(BLOCK_SIZE, working_width - x)
            if w > 0 and h > 0:
                blocks.append(Block(row=row, col=col, x=x, y=y, w=w, h=h))

    return BlockGrid(
        working_image=working_image,
        scale_to_original=scale_to_original,
        blocks=blocks,
        rows=rows,
        cols=cols,
        original_shape=(original_height, original_width),
    )


def robust_outlier_mask(
    values: np.ndarray,
    k: float = 3.0,
    min_abs_dev: float = 0.0,
) -> np.ndarray:
    """Return a median/MAD outlier mask with an absolute-deviation floor."""

    flat_values = np.asarray(values, dtype=float).reshape(-1)
    if flat_values.size == 0:
        return np.asarray([], dtype=bool)

    median_value = float(np.median(flat_values))
    deviations = np.abs(flat_values - median_value)
    mad = float(np.median(deviations))
    threshold = max(k * mad, min_abs_dev)
    return (deviations > threshold) & (deviations > min_abs_dev)


def fused_zscore(values: np.ndarray) -> np.ndarray:
    """Return robust median/MAD z-scores for a vector of block scores."""

    flat_values = np.asarray(values, dtype=float).reshape(-1)
    if flat_values.size == 0:
        return np.asarray([], dtype=float)

    median_value = float(np.median(flat_values))
    mad = float(np.median(np.abs(flat_values - median_value)))
    scale = 1.4826 * max(mad, MAD_EPSILON)
    return (flat_values - median_value) / scale


def cluster_flagged_blocks(
    grid: BlockGrid,
    flagged: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """Cluster adjacent flagged blocks into original-resolution bboxes."""

    flag_grid = _flag_grid(grid, flagged)
    if not np.any(flag_grid):
        return []

    labels, label_count = ndimage.label(flag_grid)
    bboxes = []
    for label_index in range(1, label_count + 1):
        cluster_blocks = [
            block
            for block in grid.blocks
            if labels[block.row, block.col] == label_index
        ]
        if cluster_blocks:
            bboxes.append(_merge_block_bboxes(grid, cluster_blocks))
    return bboxes


def _flag_grid(grid: BlockGrid, flagged: np.ndarray) -> np.ndarray:
    flag_grid = np.zeros((grid.rows, grid.cols), dtype=bool)
    flat_flags = np.asarray(flagged, dtype=bool).reshape(-1)
    for block, is_flagged in zip(grid.blocks, flat_flags, strict=False):
        flag_grid[block.row, block.col] = bool(is_flagged)
    return flag_grid


def _merge_block_bboxes(
    grid: BlockGrid,
    blocks: Iterable[Block],
) -> tuple[int, int, int, int]:
    x0 = min(block.x for block in blocks)
    y0 = min(block.y for block in blocks)
    x1 = max(block.x + block.w for block in blocks)
    y1 = max(block.y + block.h for block in blocks)
    return _scale_bbox_to_original(
        (x0, y0, x1 - x0, y1 - y0),
        grid.scale_to_original,
        grid.original_shape,
    )


def _scale_bbox_to_original(
    bbox: tuple[float, float, float, float],
    scale_to_original: float,
    original_shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    original_height, original_width = original_shape
    x, y, w, h = bbox
    x0 = int(round(x * scale_to_original))
    y0 = int(round(y * scale_to_original))
    x1 = int(round((x + w) * scale_to_original))
    y1 = int(round((y + h) * scale_to_original))
    x0 = max(0, min(x0, original_width))
    y0 = max(0, min(y0, original_height))
    x1 = max(x0, min(x1, original_width))
    y1 = max(y0, min(y1, original_height))
    return (x0, y0, x1 - x0, y1 - y0)
