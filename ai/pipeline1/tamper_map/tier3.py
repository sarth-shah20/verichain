"""Tier 3 spectral tamper-map corroboration."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import cv2
import fitz
import numpy as np

from pipeline1.common.page_render import get_page_images
from pipeline1.pixel_forensics.block_grid import (
    cluster_flagged_blocks,
    make_grid,
    robust_outlier_mask,
)
from pipeline1.schema import (
    ClassificationResult,
    PixelForensicsResult,
    SuspectRegion,
    TierResult,
)
from pipeline1.tamper_map.spectral import run_spectral_anomaly

SPECTRAL_IOU_THRESHOLD = 0.1
SPECTRAL_MIN_ABS_DEV = 0.01
LOW_CONFIDENCE_PENALTY = 5.0
NON_HIGH_CONFIDENCE_PENALTY_CAP = 40.0
MIN_TOTAL_BLOCKS = 10
SIGNAL_NAME = "spectral_anomaly"


def run_tier3(
    path: str | Path,
    classification: ClassificationResult,
    pixel_result: PixelForensicsResult | None,
) -> TierResult:
    """Run spectral anomaly localization and corroborate Tier 2 in place."""

    warnings: list[str] = []
    spectral_regions: list[SuspectRegion] = []
    corroborated_regions: list[SuspectRegion] = []
    spectral_ran = False
    low_confidence = False

    try:
        if classification.document_type == "scanned_image":
            for page_number, image in get_page_images(path):
                page_regions, ran = _spectral_regions_for_image(page_number, image)
                spectral_ran = spectral_ran or ran
                spectral_regions.extend(page_regions)
        elif classification.document_type in {"born_digital_pdf", "signed_pdf"}:
            for embedded in _embedded_page_images(path):
                page_regions, ran = _spectral_regions_for_image(
                    embedded.page_number,
                    embedded.image,
                    placement_rect=embedded.placement_rect,
                )
                spectral_ran = spectral_ran or ran
                spectral_regions.extend(page_regions)
        else:
            warnings.append(
                f"unsupported document type for tier3: {classification.document_type}"
            )
    except Exception as exc:
        warnings.append(f"tier3 spectral anomaly failed: {exc}")
        low_confidence = True

    standalone_regions: list[SuspectRegion] = []
    for region in spectral_regions:
        matched = _corroborate_pixel_result(region, pixel_result)
        if matched is None:
            standalone_regions.append(region)
        elif matched not in corroborated_regions:
            corroborated_regions.append(matched)

    low_count = len(standalone_regions)
    score = max(
        0.0,
        min(
            100.0,
            100.0
            - min(
                NON_HIGH_CONFIDENCE_PENALTY_CAP,
                low_count * LOW_CONFIDENCE_PENALTY,
            ),
        ),
    )

    return TierResult(
        name="tier3_spectral_anomaly",
        authenticity_score=score,
        reasons=[],
        evidence={
            "spectral_ran": spectral_ran,
            "suspect_regions": [region.model_dump() for region in standalone_regions],
            "corroborated_regions": [region.model_dump() for region in corroborated_regions],
            "low_confidence": low_confidence,
            "warnings": warnings,
        },
        confidence="low" if low_confidence else "high",
    )


class _EmbeddedImage:
    def __init__(
        self,
        page_number: int,
        image: np.ndarray,
        placement_rect: tuple[float, float, float, float],
    ) -> None:
        self.page_number = page_number
        self.image = image
        self.placement_rect = placement_rect


def _spectral_regions_for_image(
    page_number: int,
    image: np.ndarray,
    placement_rect: tuple[float, float, float, float] | None = None,
) -> tuple[list[SuspectRegion], bool]:
    try:
        grid = make_grid(image)
    except Exception:
        return [], False

    if len(grid.blocks) < MIN_TOTAL_BLOCKS:
        return [], False

    scores = run_spectral_anomaly(grid)
    flagged = robust_outlier_mask(scores, k=3.0, min_abs_dev=SPECTRAL_MIN_ABS_DEV)
    bboxes = cluster_flagged_blocks(grid, flagged)
    if placement_rect is not None:
        bboxes = [
            _map_image_bbox_to_page(bbox, image.shape[:2], placement_rect)
            for bbox in bboxes
        ]

    return [
        SuspectRegion(
            page_number=page_number,
            bbox=bbox,
            contributing_signals=[SIGNAL_NAME],
            confidence="low",
            note=f"Single-signal region from {SIGNAL_NAME}",
        )
        for bbox in bboxes
    ], True


def _embedded_page_images(path: str | Path) -> Iterable[_EmbeddedImage]:
    try:
        with fitz.open(path) as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                seen_xrefs: set[int] = set()
                for image_info in page.get_images(full=True):
                    xref = int(image_info[0])
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    image = _pixmap_to_bgr(document, xref)
                    if image is None:
                        continue
                    for rect in page.get_image_rects(xref):
                        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                            continue
                        yield _EmbeddedImage(
                            page_number=page_index + 1,
                            image=image,
                            placement_rect=(
                                float(rect.x0),
                                float(rect.y0),
                                float(rect.width),
                                float(rect.height),
                            ),
                        )
    except Exception:
        return


def _pixmap_to_bgr(document: fitz.Document, xref: int) -> np.ndarray | None:
    try:
        pixmap = fitz.Pixmap(document, xref)
        if pixmap.n - int(pixmap.alpha) > 3:
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
        if pixmap.alpha:
            pixmap = fitz.Pixmap(pixmap, 0)

        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height,
            pixmap.width,
            pixmap.n,
        )
        if pixmap.n == 1:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if pixmap.n == 3:
            return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if pixmap.n == 4:
            return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        return None
    except Exception:
        return None


def _map_image_bbox_to_page(
    bbox: tuple[int, int, int, int],
    image_shape: tuple[int, int],
    placement_rect: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    image_height, image_width = image_shape
    image_x, image_y, image_w, image_h = bbox
    rect_x, rect_y, rect_w, rect_h = placement_rect
    width_scale = rect_w / max(float(image_width), 1.0)
    height_scale = rect_h / max(float(image_height), 1.0)
    return (
        int(round(rect_x + (image_x * width_scale))),
        int(round(rect_y + (image_y * height_scale))),
        int(round(image_w * width_scale)),
        int(round(image_h * height_scale)),
    )


def _corroborate_pixel_result(
    spectral_region: SuspectRegion,
    pixel_result: PixelForensicsResult | None,
) -> SuspectRegion | None:
    if pixel_result is None:
        return None

    candidates = [
        region
        for region in pixel_result.suspect_regions
        if region.page_number == spectral_region.page_number
    ]
    match = max(
        candidates,
        key=lambda region: _bbox_iou(region.bbox, spectral_region.bbox),
        default=None,
    )
    if (
        match is None
        or _bbox_iou(match.bbox, spectral_region.bbox) <= SPECTRAL_IOU_THRESHOLD
    ):
        return None

    match.confidence = "high"
    if SIGNAL_NAME not in match.contributing_signals:
        match.contributing_signals.append(SIGNAL_NAME)
    match.note = f"Region corroborated by {', '.join(match.contributing_signals)}"
    return match


def _bbox_iou(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    left_x, left_y, left_w, left_h = left
    right_x, right_y, right_w, right_h = right
    intersection_x0 = max(left_x, right_x)
    intersection_y0 = max(left_y, right_y)
    intersection_x1 = min(left_x + left_w, right_x + right_w)
    intersection_y1 = min(left_y + left_h, right_y + right_h)
    intersection = max(0, intersection_x1 - intersection_x0) * max(
        0,
        intersection_y1 - intersection_y0,
    )
    union = (left_w * left_h) + (right_w * right_h) - intersection
    return 0.0 if union <= 0 else intersection / union
