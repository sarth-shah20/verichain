"""Tier 2 pixel-forensics localization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline1.common.page_render import get_page_images
from pipeline1.common.watermark import detect_overlay_mask
from pipeline1.pixel_forensics.block_grid import (
    BLOCK_SIZE,
    BlockGrid,
    cluster_flagged_blocks,
    fused_zscore,
    make_grid,
    robust_outlier_mask,
)
from pipeline1.pixel_forensics.copy_move import find_copy_move
from pipeline1.pixel_forensics.dct_blockmap import run_dct_anomaly
from pipeline1.pixel_forensics.ela import run_ela
from pipeline1.pixel_forensics.noise_blockmap import run_noise_anomaly
from pipeline1.schema import (
    ClassificationResult,
    PixelForensicsResult,
    SuspectRegion,
    TierResult,
    WatermarkMask,
)

MERGE_IOU_THRESHOLD = 0.1
MEDIUM_FUSED_THRESHOLD = 1.5
HIGH_CONFIDENCE_PENALTY = 25.0
MEDIUM_CONFIDENCE_PENALTY = 15.0
LOW_CONFIDENCE_PENALTY = 5.0
NON_HIGH_CONFIDENCE_PENALTY_CAP = 40.0
MIN_TOTAL_BLOCKS = 10
ELA_MIN_ABS_DEV = 2.0
DCT_MIN_ABS_DEV = 0.0
NOISE_MIN_ABS_DEV = 1.0


@dataclass
class _SignalRegion:
    page_number: int
    bbox: tuple[int, int, int, int]
    signal: str


def run_tier2(
    path: str | Path,
    classification: ClassificationResult,
    *,
    apply_watermark_suppression: bool = True,
) -> TierResult:
    """Run pixel-level forensic localization for scanned documents."""

    if classification.document_type != "scanned_image":
        return TierResult(
            name="tier2_pixel_forensics",
            authenticity_score=100.0,
            reasons=[],
            evidence={"skipped": "not applicable to this document type"},
            confidence="high",
        )

    warnings: list[str] = []
    all_signal_regions: list[_SignalRegion] = []
    medium_candidate_regions: list[SuspectRegion] = []
    ela_ran = False
    dct_ran = False
    noise_ran = False
    copy_move_ran = False
    low_confidence = False
    watermark_detected = False
    watermark_coverage = 0.0

    try:
        page_images = get_page_images(path)
        if not page_images:
            warnings.append("could not render or load pages")
            low_confidence = True

        for page_number, image in page_images:
            try:
                grid = make_grid(image)
            except Exception as exc:
                warnings.append(f"page {page_number}: could not build block grid: {exc}")
                low_confidence = True
                continue

            watermark_mask = detect_overlay_mask(image, grid)
            watermark_detected = watermark_detected or watermark_mask.detected
            watermark_coverage = max(watermark_coverage, watermark_mask.coverage_fraction)
            suppression_mask = watermark_mask if apply_watermark_suppression else None

            copy_move_regions = _copy_move_regions(page_number, grid, suppression_mask)
            if copy_move_regions:
                copy_move_ran = True
                all_signal_regions.extend(copy_move_regions)
            else:
                copy_move_ran = True

            if len(grid.blocks) < MIN_TOTAL_BLOCKS:
                warnings.append(f"page {page_number}: too few blocks for grid signals")
                low_confidence = True
                continue

            ela_scores = np.asarray(run_ela(grid).get("block_scores", []), dtype=float)
            dct_scores = run_dct_anomaly(grid)
            noise_scores = run_noise_anomaly(grid)
            ela_flagged = _watermark_suppressed_outlier_mask(
                ela_scores,
                suppression_mask,
                lambda scores: robust_outlier_mask(scores, k=3.0, min_abs_dev=ELA_MIN_ABS_DEV),
            )
            dct_flagged = _watermark_suppressed_outlier_mask(
                dct_scores,
                suppression_mask,
                lambda scores: robust_outlier_mask(scores, k=3.0, min_abs_dev=DCT_MIN_ABS_DEV),
            )
            noise_flagged = _watermark_suppressed_outlier_mask(
                noise_scores,
                suppression_mask,
                _noise_outlier_mask,
            )
            ela_regions = _regions_from_flags(page_number, grid, ela_flagged, "ela")
            dct_regions = _regions_from_flags(page_number, grid, dct_flagged, "dct")
            noise_regions = _regions_from_flags(page_number, grid, noise_flagged, "noise")
            page_signal_regions = [
                *copy_move_regions,
                *ela_regions,
                *dct_regions,
                *noise_regions,
            ]
            high_regions = [
                region
                for region in _merge_signal_regions(page_signal_regions)
                if region.confidence == "high"
            ]
            medium_candidate_regions.extend(
                _medium_regions(
                    page_number,
                    grid,
                    ela_scores,
                    dct_scores,
                    noise_scores,
                    high_regions,
                    suppression_mask,
                )
            )
            ela_ran = True
            dct_ran = True
            noise_ran = True
            all_signal_regions.extend(ela_regions)
            all_signal_regions.extend(dct_regions)
            all_signal_regions.extend(noise_regions)
    except Exception as exc:
        warnings.append(f"tier2 pixel forensics failed: {exc}")
        low_confidence = True

    high_low_regions = _merge_signal_regions(all_signal_regions)
    high_regions = [region for region in high_low_regions if region.confidence == "high"]
    medium_regions = [
        region
        for region in medium_candidate_regions
        if not _overlaps_any_high_region(region, high_regions)
    ]
    suspect_regions = [*high_low_regions, *medium_regions]
    high_count = sum(1 for region in suspect_regions if region.confidence == "high")
    medium_count = sum(1 for region in suspect_regions if region.confidence == "medium")
    low_count = sum(1 for region in suspect_regions if region.confidence == "low")
    non_high_penalty = min(
        NON_HIGH_CONFIDENCE_PENALTY_CAP,
        (medium_count * MEDIUM_CONFIDENCE_PENALTY) + (low_count * LOW_CONFIDENCE_PENALTY),
    )
    score = max(
        0.0,
        min(100.0, 100.0 - (high_count * HIGH_CONFIDENCE_PENALTY) - non_high_penalty),
    )
    reasons = [
        _reason_for_region(region)
        for region in suspect_regions
        if region.confidence in {"high", "medium"}
    ]

    result = PixelForensicsResult(
        ela_ran=ela_ran,
        dct_ran=dct_ran,
        noise_ran=noise_ran,
        copy_move_ran=copy_move_ran,
        watermark_detected=watermark_detected,
        watermark_coverage=watermark_coverage,
        suspect_regions=suspect_regions,
        low_confidence=low_confidence,
        warnings=warnings,
    )
    return TierResult(
        name="tier2_pixel_forensics",
        authenticity_score=score,
        reasons=reasons,
        evidence=result.model_dump(),
        confidence="low" if low_confidence else "high",
    )


def _ela_regions(page_number: int, grid: BlockGrid) -> list[_SignalRegion]:
    scores = np.asarray(run_ela(grid).get("block_scores", []), dtype=float)
    flagged = robust_outlier_mask(scores, k=3.0, min_abs_dev=ELA_MIN_ABS_DEV)
    return _regions_from_flags(page_number, grid, flagged, "ela")


def _dct_regions(page_number: int, grid: BlockGrid) -> list[_SignalRegion]:
    scores = run_dct_anomaly(grid)
    flagged = robust_outlier_mask(scores, k=3.0, min_abs_dev=DCT_MIN_ABS_DEV)
    return _regions_from_flags(page_number, grid, flagged, "dct")


def _noise_regions(page_number: int, grid: BlockGrid) -> list[_SignalRegion]:
    scores = run_noise_anomaly(grid)
    flagged = _noise_outlier_mask(scores)
    return _regions_from_flags(page_number, grid, flagged, "noise")


def _noise_outlier_mask(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return np.asarray([], dtype=bool)
    median_value = float(np.median(scores))
    deviations = median_value - scores
    mad = float(np.median(np.abs(scores - median_value)))
    threshold = max(3.0 * mad, NOISE_MIN_ABS_DEV)
    return (deviations > threshold) & (deviations > NOISE_MIN_ABS_DEV)


def _watermark_suppressed_outlier_mask(
    scores: np.ndarray,
    watermark_mask: WatermarkMask | None,
    detector,
) -> np.ndarray:
    flat_scores = np.asarray(scores, dtype=float).reshape(-1)
    kept_scores, kept_indices = _drop_watermark_scores(flat_scores, watermark_mask)
    kept_flags = np.asarray(detector(kept_scores), dtype=bool).reshape(-1)
    return _restore_flags(len(flat_scores), kept_indices, kept_flags)


def _drop_watermark_scores(
    scores: np.ndarray,
    watermark_mask: WatermarkMask | None,
) -> tuple[np.ndarray, np.ndarray]:
    flat_scores = np.asarray(scores, dtype=float).reshape(-1)
    flat_watermark = _flat_watermark_mask(watermark_mask, flat_scores.size)
    kept_indices = np.flatnonzero(~flat_watermark)
    return flat_scores[kept_indices], kept_indices


def _restore_flags(
    total_size: int,
    kept_indices: np.ndarray,
    kept_flags: np.ndarray,
) -> np.ndarray:
    full_flags = np.zeros(total_size, dtype=bool)
    for index, is_flagged in zip(kept_indices, kept_flags, strict=False):
        if 0 <= int(index) < total_size:
            full_flags[int(index)] = bool(is_flagged)
    return full_flags


def _medium_regions(
    page_number: int,
    grid: BlockGrid,
    ela_scores: np.ndarray,
    dct_scores: np.ndarray,
    noise_scores: np.ndarray,
    high_regions: list[SuspectRegion],
    watermark_mask: WatermarkMask | None,
) -> list[SuspectRegion]:
    if (
        ela_scores.size == 0
        or dct_scores.size == 0
        or noise_scores.size == 0
        or not (ela_scores.size == dct_scores.size == noise_scores.size)
    ):
        return []

    flat_watermark = _flat_watermark_mask(watermark_mask, ela_scores.size)
    kept_indices = np.flatnonzero(~flat_watermark)
    if kept_indices.size == 0:
        return []
    ela_scores = np.asarray(ela_scores, dtype=float).reshape(-1)[kept_indices]
    dct_scores = np.asarray(dct_scores, dtype=float).reshape(-1)[kept_indices]
    noise_scores = np.asarray(noise_scores, dtype=float).reshape(-1)[kept_indices]

    fused = np.mean(
        [
            fused_zscore(ela_scores),
            fused_zscore(dct_scores),
            -fused_zscore(noise_scores),
        ],
        axis=0,
    )
    kept_flagged = fused > MEDIUM_FUSED_THRESHOLD
    if not np.any(kept_flagged):
        return []

    flagged = _restore_flags(len(grid.blocks), kept_indices, kept_flagged)
    flagged = _exclude_high_region_blocks(grid, flagged, high_regions)
    return [
        SuspectRegion(
            page_number=page_number,
            bbox=bbox,
            contributing_signals=["ela", "dct", "noise"],
            confidence="medium",
            note="Moderate fused ELA/DCT/noise anomaly; no individual signal pair was conclusive",
        )
        for bbox in cluster_flagged_blocks(grid, flagged)
    ]


def _exclude_high_region_blocks(
    grid: BlockGrid,
    flagged: np.ndarray,
    high_regions: list[SuspectRegion],
) -> np.ndarray:
    if not high_regions:
        return flagged

    filtered = np.asarray(flagged, dtype=bool).reshape(-1).copy()
    for index, block in enumerate(grid.blocks):
        if index >= filtered.size or not filtered[index]:
            continue
        block_bbox = grid.block_bbox_original(block)
        if any(_bbox_iou(block_bbox, region.bbox) > 0.0 for region in high_regions):
            filtered[index] = False
    return filtered


def _copy_move_regions(
    page_number: int,
    grid: BlockGrid,
    watermark_mask: WatermarkMask | None,
) -> list[_SignalRegion]:
    matches = find_copy_move(grid.working_image, grid.scale_to_original)
    regions = []
    for match in matches:
        if (
            _bbox_center_in_watermark(match.source_bbox, grid, watermark_mask)
            or _bbox_center_in_watermark(match.target_bbox, grid, watermark_mask)
        ):
            continue
        regions.append(_SignalRegion(page_number, match.source_bbox, "copy_move"))
        regions.append(_SignalRegion(page_number, match.target_bbox, "copy_move"))
    return regions


def _flat_watermark_mask(
    watermark_mask: WatermarkMask | None,
    total_size: int,
) -> np.ndarray:
    if watermark_mask is None or not watermark_mask.detected or not watermark_mask.block_mask:
        return np.zeros(total_size, dtype=bool)
    flat = [
        bool(value)
        for row in watermark_mask.block_mask
        for value in row
    ]
    if len(flat) < total_size:
        flat.extend([False] * (total_size - len(flat)))
    return np.asarray(flat[:total_size], dtype=bool)


def _bbox_center_in_watermark(
    bbox: tuple[int, int, int, int],
    grid: BlockGrid,
    watermark_mask: WatermarkMask | None,
) -> bool:
    if watermark_mask is None or not watermark_mask.detected or not watermark_mask.block_mask:
        return False
    x, y, w, h = bbox
    working_x = ((float(x) + (float(w) / 2.0)) / max(grid.scale_to_original, 1e-6))
    working_y = ((float(y) + (float(h) / 2.0)) / max(grid.scale_to_original, 1e-6))
    row = int(working_y // BLOCK_SIZE)
    col = int(working_x // BLOCK_SIZE)
    if row < 0 or col < 0 or row >= len(watermark_mask.block_mask):
        return False
    if col >= len(watermark_mask.block_mask[row]):
        return False
    return bool(watermark_mask.block_mask[row][col])


def _regions_from_flags(
    page_number: int,
    grid: BlockGrid,
    flagged: np.ndarray,
    signal: str,
) -> list[_SignalRegion]:
    return [
        _SignalRegion(page_number=page_number, bbox=bbox, signal=signal)
        for bbox in cluster_flagged_blocks(grid, flagged)
    ]


def _merge_signal_regions(regions: list[_SignalRegion]) -> list[SuspectRegion]:
    if not regions:
        return []

    parent = list(range(len(regions)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left in enumerate(regions):
        for right_index in range(left_index + 1, len(regions)):
            right = regions[right_index]
            if left.page_number != right.page_number or left.signal == right.signal:
                continue
            if _bbox_iou(left.bbox, right.bbox) > MERGE_IOU_THRESHOLD:
                union(left_index, right_index)

    components: dict[int, list[_SignalRegion]] = {}
    for index, region in enumerate(regions):
        components.setdefault(find(index), []).append(region)

    suspect_regions = []
    for component_regions in components.values():
        signals = sorted({region.signal for region in component_regions})
        bbox = _merge_bboxes([region.bbox for region in component_regions])
        confidence = "high" if len(signals) >= 2 else "low"
        note = (
            f"Region corroborated by {', '.join(signals)}"
            if confidence == "high"
            else f"Single-signal region from {signals[0]}"
        )
        suspect_regions.append(
            SuspectRegion(
                page_number=component_regions[0].page_number,
                bbox=bbox,
                contributing_signals=signals,
                confidence=confidence,
                note=note,
            )
        )
    return suspect_regions


def _reason_for_region(region: SuspectRegion) -> str:
    x, y, w, h = region.bbox
    x1 = x + w
    y1 = y + h
    if region.confidence == "medium":
        return (
            f"Page {region.page_number}, region around ({x}, {y})-({x1}, {y1}): "
            "moderate fused ELA/DCT/noise anomaly, neither individually conclusive."
        )
    signals = _format_signal_list(region.contributing_signals)
    return f"Page {region.page_number}, region around ({x}, {y})-({x1}, {y1}) flagged by {signals}."


def _overlaps_any_high_region(
    region: SuspectRegion,
    high_regions: list[SuspectRegion],
) -> bool:
    return any(
        region.page_number == high_region.page_number
        and _bbox_iou(region.bbox, high_region.bbox) > 0.0
        for high_region in high_regions
    )


def _format_signal_list(signals: list[str]) -> str:
    if len(signals) == 2:
        return f"both {signals[0]} and {signals[1]} detection"
    if len(signals) > 2:
        return f"{', '.join(signals[:-1])}, and {signals[-1]} detection"
    return f"{signals[0]} detection"


def _bbox_iou(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    left_x, left_y, left_w, left_h = left
    right_x, right_y, right_w, right_h = right
    left_x1 = left_x + left_w
    left_y1 = left_y + left_h
    right_x1 = right_x + right_w
    right_y1 = right_y + right_h
    intersection_x0 = max(left_x, right_x)
    intersection_y0 = max(left_y, right_y)
    intersection_x1 = min(left_x1, right_x1)
    intersection_y1 = min(left_y1, right_y1)
    intersection = max(0, intersection_x1 - intersection_x0) * max(0, intersection_y1 - intersection_y0)
    union = (left_w * left_h) + (right_w * right_h) - intersection
    return 0.0 if union <= 0 else intersection / union


def _merge_bboxes(
    bboxes: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    x0 = min(bbox[0] for bbox in bboxes)
    y0 = min(bbox[1] for bbox in bboxes)
    x1 = max(bbox[0] + bbox[2] for bbox in bboxes)
    y1 = max(bbox[1] + bbox[3] for bbox in bboxes)
    return (x0, y0, x1 - x0, y1 - y0)
