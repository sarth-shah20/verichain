"""Visual typography forensics for scanned document images."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

import cv2
import numpy as np

from pipeline1.common.watermark import min_area_rect_slant_angle
from pipeline1.pixel_forensics.block_grid import BLOCK_SIZE
from pipeline1.schema import TypographyResult, WatermarkMask, WordFinding
from pipeline1.structure.print_artifacts import is_print_artifact_text

MIN_OCR_CONFIDENCE = 45.0
MIN_LINE_HEIGHT_PX = 8.0
MIN_ALNUM_RATIO = 0.5
MIN_WORD_LENGTH = 2
MIN_RELATIVE_WORD_HEIGHT_FRACTION = 0.15
HEADER_FOOTER_FRACTION = 0.05
LOW_CONFIDENCE_LINE_COUNT = 5
LOW_MEAN_OCR_CONFIDENCE = 40.0
OUTLIER_MAD_FACTOR = 3.0
BASELINE_RESIDUAL_FACTOR = 1.5
FEATURE_FLOORS = {
    "line_height": 2.0,
    "stroke_density": 0.03,
    "slant_angle": 3.0,
}


def analyze_typography(
    image: np.ndarray,
    scale_to_original: float = 1.0,
    page_number: int = 0,
    watermark_mask: WatermarkMask | None = None,
    grid_block_size: int | None = None,
) -> TypographyResult:
    """Analyze visual typography consistency in one loaded grayscale or BGR image."""

    result = TypographyResult()
    try:
        grayscale = _to_grayscale(image)
        if grayscale is None or grayscale.size == 0:
            result.low_confidence = True
            result.warnings.append("image is unreadable or blank")
            return result

        foreground = _binarize_foreground(grayscale)
        ocr_data = _run_ocr(grayscale)
        words, all_confidences = _extract_words(ocr_data, grayscale.shape)
        if all_confidences:
            result.mean_ocr_confidence = float(np.mean(all_confidences))

        lines = _group_lines(words)
        all_line_records = [
            _line_features(line_key, line_words, foreground)
            for line_key, line_words in lines.items()
            if len(line_words) >= 2
        ]
        all_line_records = [record for record in all_line_records if record is not None]
        _tag_header_footer_lines(
            all_line_records,
            image_shape=grayscale.shape,
            watermark_mask=watermark_mask,
            grid_block_size=grid_block_size or BLOCK_SIZE,
        )
        result.header_footer_lines = [
            _header_footer_line_summary(record)
            for record in all_line_records
            if record.get("in_header_footer")
        ]
        line_records = [
            record
            for record in all_line_records
            if not record.get("in_header_footer")
        ]
        result.qualifying_line_count = len(line_records)

        result.typography_outlier_lines = _find_typography_outliers(line_records)
        result.baseline_misaligned_words = _find_baseline_misaligned_words(line_records)
        result.outlier_findings = _outlier_word_findings(
            result.typography_outlier_lines,
            scale_to_original=scale_to_original,
            page_number=page_number,
        )
        result.baseline_findings = _baseline_word_findings(
            result.baseline_misaligned_words,
            scale_to_original=scale_to_original,
            page_number=page_number,
        )
        result.low_confidence = (
            result.qualifying_line_count < LOW_CONFIDENCE_LINE_COUNT
            or (result.mean_ocr_confidence is not None and result.mean_ocr_confidence < LOW_MEAN_OCR_CONFIDENCE)
            or result.mean_ocr_confidence is None
        )
        if result.qualifying_line_count < LOW_CONFIDENCE_LINE_COUNT:
            result.warnings.append("fewer than 5 qualifying OCR lines")
        if result.mean_ocr_confidence is None:
            result.warnings.append("no OCR words survived confidence filtering")
        elif result.mean_ocr_confidence < LOW_MEAN_OCR_CONFIDENCE:
            result.warnings.append("mean OCR confidence below 40")
    except Exception as exc:
        result.low_confidence = True
        result.warnings.append(f"typography analysis failed: {exc}")
    return result


def is_reliable_word(text: str, conf: float, height_px: float | None = None) -> bool:
    """Return whether an OCR word is reliable enough for typography analysis."""

    stripped_text = text.strip()
    if not stripped_text:
        return False
    if conf < MIN_OCR_CONFIDENCE:
        return False
    if len(stripped_text) < MIN_WORD_LENGTH:
        return False

    alnum_count = sum(1 for character in stripped_text if character.isalnum())
    return (alnum_count / len(stripped_text)) >= MIN_ALNUM_RATIO


def is_reliable_line(text: str, line_height_px: float) -> bool:
    """Return whether a grouped OCR line is reliable enough for anomaly checks."""

    stripped_text = text.strip()
    if not stripped_text:
        return False
    if line_height_px < MIN_LINE_HEIGHT_PX:
        return False

    alnum_count = sum(1 for character in stripped_text if character.isalnum())
    return (alnum_count / len(stripped_text)) >= MIN_ALNUM_RATIO


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


def _binarize_foreground(grayscale: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(grayscale, (3, 3), 0)
    _, foreground = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    return foreground


def _run_ocr(grayscale: np.ndarray) -> dict[str, list[Any]]:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise RuntimeError("pytesseract is not installed") from exc

    return pytesseract.image_to_data(grayscale, output_type=Output.DICT)


def _extract_words(
    ocr_data: dict[str, list[Any]],
    image_shape: tuple[int, ...],
) -> tuple[list[dict[str, Any]], list[float]]:
    image_height, image_width = image_shape[:2]
    words: list[dict[str, Any]] = []
    all_confidences: list[float] = []
    texts = ocr_data.get("text", [])

    for index, text in enumerate(texts):
        confidence = _safe_float(_ocr_value(ocr_data, "conf", index), default=-1.0)
        if confidence >= 0:
            all_confidences.append(confidence)
        clean_text = str(text or "").strip()

        left = int(_safe_float(_ocr_value(ocr_data, "left", index), default=0.0))
        top = int(_safe_float(_ocr_value(ocr_data, "top", index), default=0.0))
        width = int(_safe_float(_ocr_value(ocr_data, "width", index), default=0.0))
        height = int(_safe_float(_ocr_value(ocr_data, "height", index), default=0.0))
        if not is_reliable_word(clean_text, confidence):
            continue
        if width <= 0 or height <= 0:
            continue

        x0 = max(0, min(left, image_width - 1))
        y0 = max(0, min(top, image_height - 1))
        x1 = max(0, min(left + width, image_width))
        y1 = max(0, min(top + height, image_height))
        if x1 <= x0 or y1 <= y0:
            continue

        words.append(
            {
                "text": clean_text,
                "confidence": confidence,
                "bbox": [x0, y0, x1, y1],
                "block_num": int(_safe_float(_ocr_value(ocr_data, "block_num", index), default=0.0)),
                "par_num": int(_safe_float(_ocr_value(ocr_data, "par_num", index), default=0.0)),
                "line_num": int(_safe_float(_ocr_value(ocr_data, "line_num", index), default=0.0)),
                "word_num": int(_safe_float(_ocr_value(ocr_data, "word_num", index), default=0.0)),
            }
        )

    if words:
        doc_median_height = float(median([word["bbox"][3] - word["bbox"][1] for word in words]))
        min_height = MIN_RELATIVE_WORD_HEIGHT_FRACTION * doc_median_height
        # relative filter is DPI-agnostic; 15% of median is a tunable, adjust if real documents show it's too aggressive.
        words = [
            word
            for word in words
            if (word["bbox"][3] - word["bbox"][1]) >= min_height
        ]

    return words, all_confidences


def _group_lines(words: list[dict[str, Any]]) -> dict[tuple[int, int, int], list[dict[str, Any]]]:
    lines: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        key = (word["block_num"], word["par_num"], word["line_num"])
        lines[key].append(word)
    for line_words in lines.values():
        line_words.sort(key=lambda word: (word["bbox"][0], word["word_num"]))
    return lines


def _line_features(
    line_key: tuple[int, int, int],
    words: list[dict[str, Any]],
    foreground: np.ndarray,
) -> dict[str, Any] | None:
    if len(words) < 2:
        return None

    heights = [word["bbox"][3] - word["bbox"][1] for word in words]
    if not heights:
        return None

    stroke_densities = []
    slant_angles = []
    for word in words:
        x0, y0, x1, y1 = word["bbox"]
        crop = foreground[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        stroke_densities.append(float(np.count_nonzero(crop) / crop.size))
        angle = _word_slant_angle(crop)
        if angle is not None:
            slant_angles.append(angle)

    if not stroke_densities:
        stroke_densities.append(0.0)
    if not slant_angles:
        slant_angles.append(0.0)

    text = " ".join(word["text"] for word in words)
    line_height = float(median(heights))
    if not is_reliable_line(text, line_height):
        return None

    return {
        "line_key": line_key,
        "text": text,
        "words": words,
        "bbox": _line_bbox(words),
        "line_height": line_height,
        "stroke_density": float(median(stroke_densities)),
        "slant_angle": float(median(slant_angles)),
    }


def _line_bbox(words: list[dict[str, Any]]) -> list[int]:
    x0 = min(word["bbox"][0] for word in words)
    y0 = min(word["bbox"][1] for word in words)
    x1 = max(word["bbox"][2] for word in words)
    y1 = max(word["bbox"][3] for word in words)
    return [x0, y0, x1, y1]


def _tag_header_footer_lines(
    line_records: list[dict[str, Any]],
    *,
    image_height: int | None = None,
    image_shape: tuple[int, ...] | None = None,
    watermark_mask: WatermarkMask | None = None,
    grid_block_size: int = BLOCK_SIZE,
) -> None:
    if image_shape is not None:
        image_height = image_shape[0]
    if image_height is None:
        image_height = 0

    header_y_max = image_height * HEADER_FOOTER_FRACTION
    footer_y_min = image_height * (1 - HEADER_FOOTER_FRACTION)
    for record in line_records:
        centers_y = [
            (word["bbox"][1] + word["bbox"][3]) / 2.0
            for word in record["words"]
        ]
        median_center_y = float(median(centers_y)) if centers_y else 0.0
        excluded_by_position = median_center_y < header_y_max or median_center_y > footer_y_min
        excluded_by_content = is_print_artifact_text(record["text"])
        excluded_by_watermark = _line_in_watermark_block(
            record,
            watermark_mask=watermark_mask,
            image_shape=image_shape,
            grid_block_size=grid_block_size,
        )
        record["in_header_footer"] = excluded_by_position or excluded_by_content or excluded_by_watermark
        if excluded_by_watermark:
            record["exclusion_reason"] = "watermark"
        elif excluded_by_position and excluded_by_content:
            record["exclusion_reason"] = "both"
        elif excluded_by_content:
            record["exclusion_reason"] = "content"
        elif excluded_by_position:
            record["exclusion_reason"] = "position"
        else:
            record["exclusion_reason"] = None


def _line_in_watermark_block(
    record: dict[str, Any],
    *,
    watermark_mask: WatermarkMask | None,
    image_shape: tuple[int, ...] | None,
    grid_block_size: int,
) -> bool:
    if watermark_mask is None or not watermark_mask.detected or not watermark_mask.block_mask:
        return False
    bbox = record.get("bbox")
    if not bbox or len(bbox) != 4:
        return False

    block_rows = len(watermark_mask.block_mask)
    block_cols = max((len(row) for row in watermark_mask.block_mask), default=0)
    if block_rows <= 0 or block_cols <= 0:
        return False

    center_x = (float(bbox[0]) + float(bbox[2])) / 2.0
    center_y = (float(bbox[1]) + float(bbox[3])) / 2.0

    row: int
    col: int
    if image_shape is not None and len(image_shape) >= 2:
        image_height, image_width = image_shape[:2]
        expected_width = block_cols * max(1, grid_block_size)
        expected_height = block_rows * max(1, grid_block_size)
        if image_width > expected_width or image_height > expected_height:
            col = int((center_x / max(float(image_width), 1.0)) * block_cols)
            row = int((center_y / max(float(image_height), 1.0)) * block_rows)
        else:
            col = int(center_x // max(1, grid_block_size))
            row = int(center_y // max(1, grid_block_size))
    else:
        col = int(center_x // max(1, grid_block_size))
        row = int(center_y // max(1, grid_block_size))

    if row < 0 or col < 0 or row >= block_rows or col >= block_cols:
        return False
    if col >= len(watermark_mask.block_mask[row]):
        return False
    return bool(watermark_mask.block_mask[row][col])


def _header_footer_line_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": record["text"],
        "line_key": list(record["line_key"]),
        "bbox": record["bbox"],
        "word_count": len(record["words"]),
        "in_header_footer": True,
        "exclusion_reason": record.get("exclusion_reason") or "position",
    }


def _word_slant_angle(crop: np.ndarray) -> float | None:
    return min_area_rect_slant_angle(crop)


def _find_typography_outliers(line_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not line_records:
        return []

    medians = {
        feature: float(np.median([record[feature] for record in line_records]))
        for feature in FEATURE_FLOORS
    }
    mads = {
        feature: float(np.median([abs(record[feature] - medians[feature]) for record in line_records]))
        for feature in FEATURE_FLOORS
    }

    outliers = []
    for record in line_records:
        deviations = {}
        for feature, floor in FEATURE_FLOORS.items():
            deviation = abs(record[feature] - medians[feature])
            threshold = max(OUTLIER_MAD_FACTOR * mads[feature], floor)
            if deviation > threshold:
                deviations[feature] = {
                    "value": round(record[feature], 3),
                    "document_median": round(medians[feature], 3),
                    "deviation": round(deviation, 3),
                    "threshold": round(threshold, 3),
                }
        if deviations:
            outliers.append(
                {
                    "text": record["text"],
                    "line_key": list(record["line_key"]),
                    "features": {
                        "line_height": round(record["line_height"], 3),
                        "stroke_density": round(record["stroke_density"], 3),
                        "slant_angle": round(record["slant_angle"], 3),
                    },
                    "deviations": deviations,
                    "bbox": record["bbox"],
                    "words": record["words"],
                }
            )
    return outliers


def _find_baseline_misaligned_words(line_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for record in line_records:
        words = record["words"]
        if len(words) < 2:
            continue
        centers = np.asarray([(word["bbox"][0] + word["bbox"][2]) / 2.0 for word in words], dtype=float)
        bottoms = np.asarray([word["bbox"][3] for word in words], dtype=float)
        try:
            slope, intercept = np.polyfit(centers, bottoms, 1)
        except Exception:
            slope = 0.0
            intercept = float(np.median(bottoms))
        predicted = slope * centers + intercept
        threshold = BASELINE_RESIDUAL_FACTOR * record["line_height"]
        for word, residual in zip(words, bottoms - predicted, strict=False):
            if abs(float(residual)) > threshold:
                findings.append(
                    {
                        "text": word["text"],
                        "line_text": record["text"],
                        "bbox": word["bbox"],
                        "residual_px": round(float(residual), 2),
                        "threshold_px": round(float(threshold), 2),
                        "line_height": round(record["line_height"], 2),
                    }
                )
    return findings


def _outlier_word_findings(
    outlier_lines: list[dict[str, Any]],
    *,
    scale_to_original: float,
    page_number: int,
) -> list[WordFinding]:
    findings: list[WordFinding] = []
    for line in outlier_lines:
        detail = _outlier_signal_detail(line)
        for word in line.get("words", []):
            findings.append(
                WordFinding(
                    text=str(word.get("text", "")),
                    page_number=page_number,
                    bbox_original=_bbox_original(word.get("bbox"), scale_to_original),
                    finding_type="typography_outlier",
                    signal_detail=detail,
                    confidence="high",
                )
            )
    return findings


def _baseline_word_findings(
    misaligned_words: list[dict[str, Any]],
    *,
    scale_to_original: float,
    page_number: int,
) -> list[WordFinding]:
    findings: list[WordFinding] = []
    for word in misaligned_words:
        residual = float(word.get("residual_px", 0.0))
        direction = "below" if residual > 0 else "above"
        findings.append(
            WordFinding(
                text=str(word.get("text", "")),
                page_number=page_number,
                bbox_original=_bbox_original(word.get("bbox"), scale_to_original),
                finding_type="baseline_misaligned",
                signal_detail=f"{abs(residual):.0f}px {direction} baseline",
                confidence="high",
            )
        )
    return findings


def _outlier_signal_detail(line: dict[str, Any]) -> str:
    deviations = line.get("deviations", {})
    if "line_height" in deviations:
        value = float(deviations["line_height"].get("value", 0.0))
        document_median = max(float(deviations["line_height"].get("document_median", 0.0)), 0.001)
        return f"line height {value / document_median:.1f}x median"
    if "stroke_density" in deviations:
        value = float(deviations["stroke_density"].get("value", 0.0))
        document_median = max(float(deviations["stroke_density"].get("document_median", 0.0)), 0.001)
        return f"stroke density {value / document_median:.1f}x median"
    if "slant_angle" in deviations:
        deviation = float(deviations["slant_angle"].get("deviation", 0.0))
        return f"slant angle {deviation:.1f} degrees from median"
    return "typography outlier"


def _bbox_original(
    bbox: Any,
    scale_to_original: float,
) -> tuple[int, int, int, int]:
    if not bbox or len(bbox) != 4:
        return (0, 0, 0, 0)
    scale = scale_to_original if scale_to_original > 0 else 1.0
    x0, y0, x1, y1 = (float(value) / scale for value in bbox)
    return (
        int(round(x0)),
        int(round(y0)),
        max(0, int(round(x1 - x0))),
        max(0, int(round(y1 - y0))),
    )


def _ocr_value(ocr_data: dict[str, list[Any]], key: str, index: int) -> Any:
    values = ocr_data.get(key, [])
    if index >= len(values):
        return None
    return values[index]


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
