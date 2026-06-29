"""Light-gray diagonal portal watermark suppression mask."""

from __future__ import annotations

from statistics import median
from typing import TYPE_CHECKING

import cv2
import numpy as np

from pipeline1.schema import WatermarkMask

if TYPE_CHECKING:
    from pipeline1.pixel_forensics.block_grid import BlockGrid

# tuned against two real watermarked land-record scans — recheck against more samples
# before trusting blindly, especially CANDIDATE_THRESHOLD and MIN_COVERAGE.
LIGHT_BAND_LOW = 170
LIGHT_BAND_HIGH = 235
ANGLE_MIN = 15
ANGLE_MAX = 75
CANDIDATE_THRESHOLD = 0.08
MIN_COVERAGE = 0.03


def detect_overlay_mask(image: np.ndarray, grid: "BlockGrid") -> WatermarkMask:
    """Detect diagonal light-gray overlay blocks without raising on weak inputs."""

    try:
        working_image = getattr(grid, "working_image", None)
        if working_image is None or working_image.size == 0:
            working_image = image
        grayscale = _to_grayscale(working_image)
        if grayscale is None or grayscale.size == 0:
            return _empty_mask(grid)

        candidate = cv2.inRange(grayscale, LIGHT_BAND_LOW, LIGHT_BAND_HIGH)
        if candidate.size == 0 or not np.any(candidate):
            return _empty_mask(grid)

        block_mask = [[False for _ in range(grid.cols)] for _ in range(grid.rows)]
        marked_angles: list[float] = []
        for block in grid.blocks:
            crop = candidate[block.y : block.y + block.h, block.x : block.x + block.w]
            if crop.size == 0:
                continue
            candidate_fraction = float(np.count_nonzero(crop) / crop.size)
            if candidate_fraction <= CANDIDATE_THRESHOLD:
                continue
            angle = _qualifying_angle(crop)
            if angle is None:
                continue
            block_mask[block.row][block.col] = True
            marked_angles.append(angle)

        coverage_fraction = (
            float(np.mean(np.asarray(block_mask, dtype=bool)))
            if grid.rows > 0 and grid.cols > 0
            else 0.0
        )
        detected = coverage_fraction > MIN_COVERAGE
        if not detected:
            block_mask = [[False for _ in range(grid.cols)] for _ in range(grid.rows)]
            marked_angles = []

        return WatermarkMask(
            detected=detected,
            coverage_fraction=coverage_fraction if detected else 0.0,
            dominant_angle_deg=_circular_median(marked_angles) if detected else None,
            block_mask=block_mask,
            method="light_gray_band+diagonal_min_area_rect" if detected else "",
        )
    except Exception:
        return _empty_mask(grid)


def _to_grayscale(image: np.ndarray) -> np.ndarray | None:
    if image is None:
        return None
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return None


def _qualifying_angle(candidate_crop: np.ndarray) -> float | None:
    label_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (candidate_crop > 0).astype(np.uint8),
        connectivity=8,
    )
    angles = []
    for label_index in range(1, label_count):
        if int(stats[label_index, cv2.CC_STAT_AREA]) < 3:
            continue
        component = np.zeros(candidate_crop.shape, dtype=np.uint8)
        component[labels == label_index] = 255
        angle = min_area_rect_slant_angle(component)
        if angle is None:
            continue
        angle_from_axis = abs(float(angle))
        if ANGLE_MIN <= angle_from_axis <= ANGLE_MAX:
            angles.append(float(angle))
    if not angles:
        return None
    return float(median(angles))


def min_area_rect_slant_angle(crop: np.ndarray) -> float | None:
    """Return the normalized minAreaRect angle used by typography slant checks."""

    contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    points = []
    for contour in contours:
        if cv2.contourArea(contour) > 1:
            points.extend(contour.reshape(-1, 2))
    if len(points) < 3:
        return None

    rect = cv2.minAreaRect(np.asarray(points, dtype=np.float32))
    angle = float(rect[-1])
    if angle < -45.0:
        angle += 90.0
    if angle > 45.0:
        angle -= 90.0
    return angle


def _circular_median(angles: list[float]) -> float | None:
    if not angles:
        return None
    normalized = [((float(angle) + 90.0) % 180.0) - 90.0 for angle in angles]

    def distance_sum(candidate: float) -> float:
        return sum(_axial_distance(candidate, angle) for angle in normalized)

    return round(float(min(normalized, key=distance_sum)), 3)


def _axial_distance(left: float, right: float) -> float:
    delta = abs(left - right) % 180.0
    return min(delta, 180.0 - delta)


def _empty_mask(grid: "BlockGrid") -> WatermarkMask:
    rows = max(0, int(getattr(grid, "rows", 0)))
    cols = max(0, int(getattr(grid, "cols", 0)))
    return WatermarkMask(
        detected=False,
        coverage_fraction=0.0,
        dominant_angle_deg=None,
        block_mask=[[False for _ in range(cols)] for _ in range(rows)],
        method="",
    )
