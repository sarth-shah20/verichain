"""Offline document classifier for Pipeline 1 forensic routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import fitz
import pikepdf
from pikepdf import Name, PasswordError

from pipeline1.schema import ClassificationResult

MAX_PAGES_TO_CHECK = 5
TEXT_LENGTH_THRESHOLD = 40
IMAGE_COVERAGE_THRESHOLD = 0.60
MIXED_PAGE_WARNING = "mixed page types detected"


def classify(path: str | Path) -> ClassificationResult:
    """Classify a PDF or image-like document for downstream forensic checks.

    The classifier is deliberately structural and fully offline. It detects
    embedded PDF signature dictionaries, estimates whether unsigned PDFs are
    born-digital or scan-like, and always returns a routing result even for
    malformed inputs.

    Args:
        path: File path to a PDF or image-like document.

    Returns:
        A :class:`ClassificationResult` describing the selected route.
    """

    file_path = Path(path)
    warnings: list[str] = []

    try:
        is_pdf_candidate = _looks_like_pdf(file_path)
    except OSError as exc:
        return _scanned_result(
            page_count=1,
            is_encrypted=False,
            warnings=[f"could not inspect file header: {exc}"],
        )

    if not is_pdf_candidate:
        return _scanned_result(page_count=1, is_encrypted=False, warnings=warnings)

    try:
        with pikepdf.open(file_path) as pdf:
            page_count = len(pdf.pages)
            is_encrypted = bool(getattr(pdf, "is_encrypted", False))
            has_signature = _has_embedded_signature(pdf)
    except PasswordError as exc:
        return _scanned_result(
            page_count=0,
            is_encrypted=True,
            warnings=[f"PDF is encrypted or password-protected and could not be opened: {exc}"],
        )
    except (pikepdf.PdfError, OSError, ValueError) as exc:
        return _scanned_result(
            page_count=0,
            is_encrypted=False,
            warnings=[f"PDF could not be parsed: {exc}"],
        )
    except Exception as exc:  # Defensive routing for malformed edge cases.
        return _scanned_result(
            page_count=0,
            is_encrypted=False,
            warnings=[f"unexpected PDF parsing error: {exc}"],
        )

    if has_signature:
        return ClassificationResult(
            document_type="signed_pdf",
            page_count=page_count,
            has_embedded_signature=True,
            vector_text_ratio=0.0,
            is_encrypted=is_encrypted,
            warnings=warnings,
        )

    try:
        vector_text_ratio, page_type_warnings = _estimate_vector_text_ratio(file_path)
        warnings.extend(page_type_warnings)
    except Exception as exc:  # PyMuPDF can raise many exception subclasses.
        return _scanned_result(
            page_count=page_count,
            is_encrypted=is_encrypted,
            warnings=[*warnings, f"PDF page analysis failed: {exc}"],
        )

    document_type = (
        "born_digital_pdf" if vector_text_ratio >= 0.60 else "scanned_image"
    )
    return ClassificationResult(
        document_type=document_type,
        page_count=page_count,
        has_embedded_signature=False,
        vector_text_ratio=vector_text_ratio,
        is_encrypted=is_encrypted,
        warnings=warnings,
    )


def _looks_like_pdf(path: Path) -> bool:
    """Return whether a file should be treated as a PDF candidate."""

    has_pdf_extension = path.suffix.lower() == ".pdf"
    with path.open("rb") as file:
        header = file.read(5)
    has_pdf_magic = header == b"%PDF-"
    return has_pdf_extension or has_pdf_magic


def _has_embedded_signature(pdf: pikepdf.Pdf) -> bool:
    """Return whether the PDF AcroForm contains a signature dictionary."""

    root = pdf.Root
    acroform = _dict_get(root, "/AcroForm")
    if acroform is None:
        return False

    fields = _dict_get(acroform, "/Fields")
    if fields is None:
        return False

    return any(_field_has_signature(field) for field in fields)


def _field_has_signature(field: Any) -> bool:
    """Recursively inspect an AcroForm field for a PDF signature dictionary."""

    if _has_signature_payload(field):
        return True

    value = _dict_get(field, "/V")
    if value is not None and _has_signature_payload(value):
        return True

    kids = _dict_get(field, "/Kids")
    if kids is None:
        return False

    return any(_field_has_signature(kid) for kid in kids)


def _has_signature_payload(value: Any) -> bool:
    """Return whether an object has both signature payload keys."""

    return _dict_get(value, "/ByteRange") is not None and _dict_get(value, "/Contents") is not None


def _dict_get(mapping: Any, key: str) -> Any | None:
    """Safely read a PDF dictionary key from pikepdf objects."""

    try:
        return mapping.get(Name(key))
    except Exception:
        return None


def _estimate_vector_text_ratio(path: Path) -> tuple[float, list[str]]:
    """Estimate the fraction of checked pages that are mostly vector text."""

    warnings: list[str] = []
    with fitz.open(path) as document:
        checked_pages = min(document.page_count, MAX_PAGES_TO_CHECK)
        if checked_pages == 0:
            return 0.0, ["PDF has no pages"]

        vector_text_pages = 0
        for page_index in range(checked_pages):
            page = document.load_page(page_index)
            if _is_mostly_vector_text_page(page):
                vector_text_pages += 1

    ratio = vector_text_pages / checked_pages
    if checked_pages > 1 and 0 < vector_text_pages < checked_pages:
        warnings.append(MIXED_PAGE_WARNING)

    return ratio, warnings


def _is_mostly_vector_text_page(page: fitz.Page) -> bool:
    """Return whether a page has enough text and limited raster coverage."""

    text_length = len(page.get_text("text").strip())
    image_coverage = _raster_image_coverage(page)
    return (
        text_length >= TEXT_LENGTH_THRESHOLD
        and image_coverage < IMAGE_COVERAGE_THRESHOLD
    )


def _raster_image_coverage(page: fitz.Page) -> float:
    """Estimate raster image area as a fraction of page area."""

    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    image_area = 0.0

    text_page = page.get_text("dict")
    for block in text_page.get("blocks", []):
        if block.get("type") != 1:
            continue
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in bbox)
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        image_area += width * height

    return min(image_area / page_area, 1.0)


def _scanned_result(
    *,
    page_count: int,
    is_encrypted: bool,
    warnings: list[str],
) -> ClassificationResult:
    """Build a scan-like fallback result."""

    return ClassificationResult(
        document_type="scanned_image",
        page_count=page_count,
        has_embedded_signature=False,
        vector_text_ratio=0.0,
        is_encrypted=is_encrypted,
        warnings=warnings,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: python -m pipeline1.classifier <path>"}))
        raise SystemExit(2)

    result = classify(sys.argv[1])
    print(result.model_dump_json(indent=2))
