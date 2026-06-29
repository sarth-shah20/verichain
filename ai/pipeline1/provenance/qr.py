"""Offline QR-code extraction for documents and images."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import fitz
from PIL import Image

from pipeline1.schema import QRCheckResult, QRResult

LOGGER = logging.getLogger(__name__)
PDF_RENDER_DPI = 200


def find_qr_codes(path: str | Path) -> list[QRResult]:
    """Decode QR payloads from a PDF or image file.

    The function never raises for missing decoders, corrupt documents, or files
    without QR codes; those cases simply return an empty list.
    """

    file_path = Path(path)
    try:
        if _looks_like_pdf(file_path):
            images = _render_pdf_pages(file_path)
        else:
            images = [(0, _open_image(file_path))]

        results: list[QRResult] = []
        for page_number, image in images:
            results.extend(_decode_image(image, page_number))
        return _dedupe_results(results)
    except Exception as exc:
        LOGGER.warning("QR decode failed for %s: %s", file_path, exc)
        return []


def decode_qr_from_file(path: str | Path) -> list[str]:
    """Backward-compatible wrapper returning only decoded payload strings."""

    return _dedupe([result.payload for result in find_qr_codes(path)])


def check_qr_against_registry(
    qr_payloads: list[str],
    file_bytes: bytes,
    registry: object,
) -> QRCheckResult:
    """Legacy registry helper retained for older callers.

    New code should use ``mock_registry.lookup_by_qr_payload`` and
    ``mock_registry.lookup_by_hash`` directly.
    """

    import hashlib

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    matched_records = []
    for payload in qr_payloads:
        lookup = getattr(registry, "lookup_by_qr_payload", None)
        if callable(lookup):
            record = lookup(payload)
            if record is not None:
                matched_records.append(record)

    registry_match = bool(matched_records)
    content_hash_match = any(
        getattr(record, "doc_sha256", None) == file_hash for record in matched_records
    )

    reasons: list[str] = []
    if not qr_payloads:
        reasons.append("No QR found")
    elif not registry_match:
        reasons.append("QR found but not in registry")
    elif not content_hash_match:
        reasons.append("QR registry match found but content hash mismatch")

    return QRCheckResult(
        qr_found=bool(qr_payloads),
        payloads_decoded=qr_payloads,
        registry_match=registry_match,
        content_hash_match=content_hash_match,
        reasons=reasons,
    )


def _looks_like_pdf(path: Path) -> bool:
    """Return whether the file should be treated as a PDF candidate."""

    if path.suffix.lower() == ".pdf":
        return True
    try:
        with path.open("rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def _render_pdf_pages(path: Path) -> list[tuple[int, Image.Image]]:
    """Render PDF pages to RGB PIL images at the configured DPI."""

    images: list[tuple[int, Image.Image]] = []
    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            images.append((page_index + 1, image))
    return images


def _open_image(path: Path) -> Image.Image:
    """Open an image file and normalise it to RGB."""

    with Image.open(path) as image:
        return image.convert("RGB")


def _decode_image(image: Image.Image, page_number: int) -> list[QRResult]:
    """Decode QR payloads from one page/image using staged fallbacks."""

    direct_payloads = _decode_with_pyzbar(image)
    if direct_payloads:
        return [
            QRResult(
                payload=payload,
                page_number=page_number,
                decoded_via_fallback=False,
            )
            for payload in direct_payloads
        ]

    preprocessed = _preprocess_for_qr(image)
    fallback_payloads = _decode_with_pyzbar(preprocessed)
    if not fallback_payloads:
        fallback_payloads = _decode_with_opencv(image)
    if not fallback_payloads:
        fallback_payloads = _decode_with_opencv(preprocessed)

    return [
        QRResult(
            payload=payload,
            page_number=page_number,
            decoded_via_fallback=True,
        )
        for payload in fallback_payloads
    ]


def _preprocess_for_qr(image: Image.Image) -> Image.Image:
    """Apply light grayscale and adaptive-threshold preprocessing."""

    try:
        import cv2
        import numpy as np
    except Exception:
        return image.convert("L")

    grayscale = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    thresholded = cv2.adaptiveThreshold(
        grayscale,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    return Image.fromarray(thresholded)


def _decode_with_pyzbar(image: Image.Image) -> list[str]:
    """Decode QR payloads with pyzbar if its local zbar dependency exists."""

    try:
        from pyzbar.pyzbar import decode
    except Exception as exc:
        LOGGER.debug("pyzbar unavailable: %s", exc)
        return []

    try:
        return [
            item.data.decode("utf-8", errors="replace")
            for item in decode(image)
            if getattr(item, "data", None)
        ]
    except Exception as exc:
        LOGGER.warning("pyzbar QR decode failed: %s", exc)
        return []


def _decode_with_opencv(image: Image.Image) -> list[str]:
    """Decode QR payloads with OpenCV's QRCodeDetector fallback."""

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        LOGGER.debug("OpenCV QR decoder unavailable: %s", exc)
        return []

    try:
        image_array = np.array(image.convert("RGB"))
        detector = cv2.QRCodeDetector()

        payloads = _opencv_detect_multi(detector, image_array)
        if payloads:
            return payloads

        payload, _, _ = detector.detectAndDecode(image_array)
        return [payload] if payload else []
    except Exception as exc:
        LOGGER.warning("OpenCV QR decode failed: %s", exc)
        return []


def _opencv_detect_multi(detector: object, image_array: object) -> list[str]:
    """Return payloads from OpenCV's multi-QR API when available."""

    detect_multi = getattr(detector, "detectAndDecodeMulti", None)
    if detect_multi is None:
        return []

    result = detect_multi(image_array)
    if not isinstance(result, tuple) or len(result) < 2:
        return []

    decoded_info = result[1]
    return [payload for payload in decoded_info if payload]


def _dedupe_results(results: Iterable[QRResult]) -> list[QRResult]:
    """Deduplicate payload/page pairs while preserving first decoder metadata."""

    seen: set[tuple[str, int]] = set()
    deduped: list[QRResult] = []
    for result in results:
        key = (result.payload, result.page_number)
        if key not in seen:
            seen.add(key)
            deduped.append(result)
    return deduped


def _dedupe(payloads: Iterable[str]) -> list[str]:
    """Deduplicate decoded payloads while preserving order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for payload in payloads:
        if payload not in seen:
            seen.add(payload)
            deduped.append(payload)
    return deduped
