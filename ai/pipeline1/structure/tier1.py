"""Tier 1 structure and typography forensics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from pipeline1.common.watermark import detect_overlay_mask
from pipeline1.pixel_forensics.block_grid import BLOCK_SIZE, make_grid
from pipeline1.common.page_render import get_page_images
from pipeline1.schema import (
    ClassificationResult,
    ExifResult,
    FontSpanFinding,
    TierResult,
    TypographyResult,
    WordFinding,
)
from pipeline1.structure.exif_metadata import check_exif
from pipeline1.structure.pdf_metadata import check_pdf_metadata
from pipeline1.structure.revision_recovery import recover_revisions
from pipeline1.structure.visual_typography import analyze_typography

BORN_DIGITAL_TYPES = {"signed_pdf", "born_digital_pdf"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".png"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
MAX_SCANNED_PDF_PAGES = 3


def run_tier1(path: str | Path, classification: ClassificationResult) -> TierResult:
    """Run Tier 1 checks based on the classifier route."""

    file_path = Path(path)
    reasons: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {}
    score = 100.0
    confidence = "high"
    structure_regions: list[dict[str, Any]] = []

    if classification.document_type in BORN_DIGITAL_TYPES:
        pdf_result = check_pdf_metadata(file_path)
        evidence["pdf_metadata"] = pdf_result.model_dump()
        evidence["font_style_variants"] = [
            finding.model_dump() for finding in pdf_result.font_style_variants
        ]
        evidence["font_findings"] = [
            {
                "text": ff.text,
                "page": ff.page_number,
                "bbox_pts": list(ff.bbox_pts),
                "font": ff.font_name,
                "detail": "font family mismatch",
            }
            for ff in pdf_result.font_family_mismatches
        ]
        for ff in pdf_result.font_family_mismatches:
            structure_regions.append(
                {
                    "page_number": ff.page_number,
                    "bbox_pts": list(ff.bbox_pts),
                    "signal": "font_mismatch",
                    "confidence": "medium",
                    "note": f"Font '{ff.font_name}' deviates from document dominant",
                }
            )
        for ff in pdf_result.font_style_variants:
            structure_regions.append(
                {
                    "page_number": ff.page_number,
                    "bbox_pts": list(ff.bbox_pts),
                    "signal": "font_style_variant",
                    # Typed government templates routinely use a bold accent font;
                    # treat as advisory only, never a clickable box by itself.
                    "confidence": "low",
                    "note": f"Unexpected font style '{ff.font_name}' on '{ff.text[:24]}'",
                }
            )
        pdf_reasons, pdf_penalty = _pdf_reasons(pdf_result)
        reasons.extend(pdf_reasons)
        score -= pdf_penalty
        warnings.extend(pdf_result.warnings)
        if pdf_result.warnings:
            confidence = "medium"

    # Revision recovery runs for ANY PDF (born-digital or scanned): the killer
    # tamper artifact. It reconstructs the prior incremental-update revision and
    # recovers the ORIGINAL value of any edited field, promoting incremental-
    # update analysis from a bare metadata flag to first-class before/after
    # evidence. Silent (no penalty) on single-revision or benign-resave PDFs.
    if file_path.suffix.lower() == ".pdf":
        try:
            revision = recover_revisions(file_path)
            evidence["revision_recovery"] = revision.model_dump()
            rev_reasons, rev_penalty = _revision_reasons(revision)
            reasons.extend(rev_reasons)
            score -= rev_penalty
            for c in revision.recovered_changes:
                structure_regions.append(
                    {
                        "page_number": c.page_number,
                        "bbox_pts": list(c.bbox) if c.bbox else None,
                        "signal": "revision_edit",
                        "confidence": "high" if c.weight == "high" else "medium",
                        "note": (
                            f"Recovered revision edit — "
                            f"{c.field_hint or 'field'}: {c.original_value} → {c.current_value}"
                        ),
                    }
                )
        except Exception as exc:  # never let recovery sink the tier
            warnings.append(f"revision recovery failed: {exc}")

    if classification.document_type == "scanned_image":
        typography_results, render_warnings = _analyze_scanned_document(file_path)
        evidence["typography"] = [result.model_dump() for result in typography_results]
        evidence["word_findings"] = [
            {
                "text": wf.text,
                "page": wf.page_number,
                "bbox": list(wf.bbox_original),
                "type": wf.finding_type,
                "detail": wf.signal_detail,
                "confidence": wf.confidence,
            }
            for result in typography_results
            for wf in (result.outlier_findings + result.baseline_findings)
        ]
        warnings.extend(render_warnings)
        typography_reasons, typography_penalty = _typography_reasons(typography_results)
        reasons.extend(typography_reasons)
        score -= typography_penalty
        if render_warnings or not typography_results or any(result.low_confidence for result in typography_results):
            confidence = "low"

    if _is_photo_file(file_path):
        exif_result = check_exif(file_path)
        evidence["exif"] = exif_result.model_dump()
        exif_reasons, exif_penalty = _exif_reasons(exif_result)
        reasons.extend(exif_reasons)
        score -= exif_penalty
        warnings.extend(exif_result.warnings)
        if exif_result.warnings and confidence == "high":
            confidence = "medium"

    if warnings:
        evidence["warnings"] = warnings
    if structure_regions:
        evidence["structure_regions"] = structure_regions

    return TierResult(
        name="tier1_structure_typography",
        authenticity_score=max(0.0, min(100.0, score)),
        reasons=reasons,
        evidence=evidence or None,
        confidence=confidence,
    )


def _analyze_scanned_document(file_path: Path) -> tuple[list[TypographyResult], list[str]]:
    warnings: list[str] = []
    results: list[TypographyResult] = []

    if _is_image_file(file_path):
        page_images = get_page_images(file_path)
        if not page_images:
            return [
                analyze_typography(
                    np.asarray([]),
                    scale_to_original=1.0,
                    page_number=0,
                )
            ], [f"could not load image: {file_path.name}"]
        return [
            _analyze_image_typography(page_images[0][1], page_number=0)
        ], warnings

    if file_path.suffix.lower() == ".pdf":
        page_images = get_page_images(file_path)
        if not page_images:
            warnings.append("could not render scanned PDF pages")
            results.append(
                analyze_typography(
                    np.asarray([]),
                    scale_to_original=1.0,
                    page_number=0,
                )
            )
            return results, warnings
        for rendered_page_number, image in page_images[:MAX_SCANNED_PDF_PAGES]:
            results.append(
                _analyze_image_typography(
                    image,
                    page_number=max(0, rendered_page_number - 1),
                )
            )
        return results, warnings

    results.append(
        analyze_typography(
            np.asarray([]),
            scale_to_original=1.0,
            page_number=0,
        )
    )
    warnings.append(f"unsupported scanned document format: {file_path.suffix or '<none>'}")
    return results, warnings


def _analyze_image_typography(image: np.ndarray, *, page_number: int) -> TypographyResult:
    try:
        grid = make_grid(image)
        watermark_mask = detect_overlay_mask(image, grid)
    except Exception:
        watermark_mask = None
    return analyze_typography(
        image,
        scale_to_original=1.0,
        page_number=page_number,
        watermark_mask=watermark_mask,
        grid_block_size=BLOCK_SIZE,
    )


def _pdf_reasons(pdf_result) -> tuple[list[str], float]:
    reasons = []
    penalty = 0.0
    if pdf_result.modified_after_creation:
        days = pdf_result.modification_delta_days
        if days is None:
            reasons.append("PDF ModDate is meaningfully after CreationDate")
        else:
            reasons.append(f"PDF ModDate is {days:.2f} days after CreationDate")
        penalty += 10.0
    if pdf_result.incremental_update_detected:
        reasons.append("PDF contains multiple startxref sections, suggesting an incremental re-save")
        penalty += 10.0
    if pdf_result.font_family_mismatches:
        reasons.extend(
            _format_font_mismatch_reason(finding, pdf_result.dominant_font)
            for finding in pdf_result.font_family_mismatches
        )
        penalty += min(30.0, 12.0 + 3.0 * len(pdf_result.font_family_mismatches))
    return reasons, penalty


def _revision_reasons(revision) -> tuple[list[str], float]:
    """Field-weighted reasons + penalty from recovered before/after edits.

    A recovered material edit is HARD evidence (the original bytes are still in
    the file), not a soft pixel heuristic, so it carries a real penalty — and it
    corroborates any Pipeline-2 content mismatch on the same field.
    """
    reasons: list[str] = []
    penalty = 0.0
    if not revision.prior_revision_recovered:
        return reasons, penalty

    high = [c for c in revision.recovered_changes if c.weight == "high"]
    medium = [c for c in revision.recovered_changes if c.weight == "medium"]

    for c in high:
        label = f"{c.field_hint}: " if c.field_hint else ""
        reasons.append(
            f"Recovered prior PDF revision — {label}original '{c.original_value}' "
            f"was edited to '{c.current_value}' (incremental-update tamper)"
        )
    for c in medium:
        label = f"{c.field_hint}: " if c.field_hint else ""
        reasons.append(
            f"Recovered prior PDF revision — {label}'{c.original_value}' "
            f"changed to '{c.current_value}'"
        )

    if high:
        penalty += min(45.0, 30.0 + 5.0 * len(high))
    elif medium:
        penalty += min(25.0, 15.0 + 5.0 * len(medium))
    return reasons, penalty


def _typography_reasons(results: list[TypographyResult]) -> tuple[list[str], float]:
    reasons = []
    penalty = 0.0
    for result in results:
        for finding in result.outlier_findings + result.baseline_findings:
            if finding.confidence == "high":
                reasons.append(_format_word_finding_reason(finding))
    outlier_count = sum(len(result.typography_outlier_lines) for result in results)
    baseline_count = sum(len(result.baseline_misaligned_words) for result in results)
    if outlier_count:
        penalty += min(35.0, 12.0 + 4.0 * outlier_count)
    if baseline_count:
        penalty += min(35.0, 15.0 + 5.0 * baseline_count)
    return reasons, penalty


def _format_word_finding_reason(finding: WordFinding) -> str:
    bbox = ",".join(str(value) for value in finding.bbox_original)
    if finding.finding_type == "baseline_misaligned":
        return (
            f"Word '{finding.text}' sits {finding.signal_detail} "
            f"[bbox: {bbox}]"
        )
    return (
        f"Word '{finding.text}' is a typography outlier: {finding.signal_detail} "
        f"[bbox: {bbox}]"
    )


def _format_font_mismatch_reason(
    finding: FontSpanFinding,
    dominant_font: str | None,
) -> str:
    bbox = ",".join(f"{value:.1f}" for value in finding.bbox_pts)
    dominant = dominant_font or "unknown"
    return (
        f"Field '{finding.text}' uses font '{finding.font_name}' vs document dominant "
        f"'{dominant}' [page {finding.page_number}, bbox_pts: {bbox}]"
    )


def _format_line_outlier_reason(line: dict[str, Any]) -> str:
    text = str(line.get("text", "")).strip()
    deviations = line.get("deviations", {})
    if "stroke_density" in deviations:
        value = deviations["stroke_density"].get("value", 0.0)
        median = max(float(deviations["stroke_density"].get("document_median", 0.0)), 0.001)
        return f"Line '{text}' has stroke density {float(value) / median:.1f}x the document median"
    if "line_height" in deviations:
        deviation = deviations["line_height"].get("deviation", 0.0)
        return f"Line '{text}' has text height {float(deviation):.0f}px from the document median"
    if "slant_angle" in deviations:
        deviation = deviations["slant_angle"].get("deviation", 0.0)
        return f"Line '{text}' has slant angle {float(deviation):.1f} degrees from the document median"
    return f"Line '{text}' is a typography outlier"


def _exif_reasons(exif_result: ExifResult) -> tuple[list[str], float]:
    if not exif_result.suspicious_software_detected:
        return [], 0.0
    software = exif_result.software or "unknown editor"
    return [f"Photo EXIF Software tag mentions {software}"], 15.0


def _is_photo_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in PHOTO_EXTENSIONS


def _is_image_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in IMAGE_EXTENSIONS
