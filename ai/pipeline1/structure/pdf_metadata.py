"""Born-digital PDF metadata and embedded typography checks."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

import fitz
import pikepdf
from pikepdf import Name, PasswordError

from pipeline1.schema import FontSpanFinding, PdfMetadataResult
from pipeline1.structure.font_utils import font_style_tokens, normalize_font_family
from pipeline1.structure.print_artifacts import is_print_artifact_text

MEANINGFUL_MODIFICATION_DAYS = 1.0 / 24.0
PDF_HEADER_MARGIN_PT = 50.0
PDF_FOOTER_MARGIN_PT = 50.0
PDF_DATE_RE = re.compile(
    r"^D:(?P<year>\d{4})"
    r"(?P<month>\d{2})?"
    r"(?P<day>\d{2})?"
    r"(?P<hour>\d{2})?"
    r"(?P<minute>\d{2})?"
    r"(?P<second>\d{2})?"
    r"(?P<offset>Z|[+-]\d{2}'?\d{2}'?)?$"
)


def check_pdf_metadata(path: str | Path) -> PdfMetadataResult:
    """Inspect PDF metadata, save structure, and embedded text fonts."""

    file_path = Path(path)
    result = PdfMetadataResult()

    try:
        _populate_docinfo(file_path, result)
    except PasswordError as exc:
        result.warnings.append(f"PDF is encrypted or password-protected: {exc}")
    except (pikepdf.PdfError, OSError, ValueError) as exc:
        result.warnings.append(f"PDF metadata could not be parsed: {exc}")
    except Exception as exc:
        result.warnings.append(f"unexpected PDF metadata error: {exc}")

    try:
        raw_bytes = file_path.read_bytes()
        # Heuristic: each incremental update normally appends a new xref section.
        result.startxref_count = raw_bytes.count(b"startxref")
        result.incremental_update_detected = result.startxref_count > 1
    except OSError as exc:
        result.warnings.append(f"could not read raw PDF bytes: {exc}")

    try:
        _populate_font_findings(file_path, result)
    except Exception as exc:
        result.warnings.append(f"PDF text/font inspection failed: {exc}")

    return result


def _populate_docinfo(file_path: Path, result: PdfMetadataResult) -> None:
    with pikepdf.open(file_path) as pdf:
        docinfo = pdf.docinfo
        result.producer = _pdf_value_to_str(docinfo.get(Name("/Producer")))
        result.creator = _pdf_value_to_str(docinfo.get(Name("/Creator")))
        raw_creation_date = _pdf_value_to_str(docinfo.get(Name("/CreationDate")))
        raw_mod_date = _pdf_value_to_str(docinfo.get(Name("/ModDate")))
        result.creation_date = raw_creation_date
        result.mod_date = raw_mod_date

    creation_date = _parse_pdf_date(raw_creation_date)
    mod_date = _parse_pdf_date(raw_mod_date)
    if raw_creation_date and creation_date is None:
        result.warnings.append(f"could not parse CreationDate: {raw_creation_date}")
    if raw_mod_date and mod_date is None:
        result.warnings.append(f"could not parse ModDate: {raw_mod_date}")
    if creation_date is None or mod_date is None:
        return

    delta_days = (mod_date - creation_date).total_seconds() / 86400.0
    result.modification_delta_days = delta_days
    result.modified_after_creation = delta_days > MEANINGFUL_MODIFICATION_DAYS


def _populate_font_findings(file_path: Path, result: PdfMetadataResult) -> None:
    spans = []
    with fitz.open(file_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_height = float(page.rect.height)
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font_name = span.get("font")
                        text = span.get("text", "")
                        bbox = span.get("bbox")
                        if not font_name or not text:
                            continue
                        bbox_pts = _normalise_bbox(bbox)
                        if bbox_pts is None:
                            continue
                        normalized_family = normalize_font_family(str(font_name))
                        span_record = {
                            "font_name": str(font_name),
                            "font_family_normalized": normalized_family,
                            "style_tokens": sorted(font_style_tokens(str(font_name))),
                            "text": str(text),
                            "bbox_pts": bbox_pts,
                            "page_number": page_index + 1,
                        }
                        excluded_by_position = _is_header_or_footer_span(bbox_pts, page_height)
                        excluded_by_content = is_print_artifact_text(str(text))
                        if excluded_by_position or excluded_by_content:
                            result.header_footer_spans.append(
                                {
                                    **_span_finding(span_record).model_dump(),
                                    "in_header_footer": True,
                                    "exclusion_reason": _exclusion_reason(
                                        excluded_by_position,
                                        excluded_by_content,
                                    ),
                                }
                            )
                            continue
                        spans.append(span_record)

    if not spans:
        return

    family_counts = Counter(span["font_family_normalized"] for span in spans)
    dominant_family = family_counts.most_common(1)[0][0]
    result.dominant_font = dominant_family

    dominant_raw_font = Counter(
        span["font_name"]
        for span in spans
        if span["font_family_normalized"] == dominant_family
    ).most_common(1)[0][0]

    result.font_family_mismatches = [
        _span_finding(span)
        for span in spans
        if span["font_family_normalized"] != dominant_family
        and any(character.isdigit() for character in span["text"])
    ]
    result.font_style_variants = [
        _span_finding(span)
        for span in spans
        if span["font_family_normalized"] == dominant_family
        and span["font_name"] != dominant_raw_font
        and any(character.isdigit() for character in span["text"])
    ]


def _span_finding(span: dict[str, Any]) -> FontSpanFinding:
    return FontSpanFinding(
        text=str(span["text"]),
        font_name=str(span["font_name"]),
        font_family_normalized=str(span["font_family_normalized"]),
        bbox_pts=tuple(float(value) for value in span["bbox_pts"]),
        page_number=int(span["page_number"]),
    )


def _exclusion_reason(
    excluded_by_position: bool,
    excluded_by_content: bool,
) -> str:
    if excluded_by_position and excluded_by_content:
        return "both"
    if excluded_by_content:
        return "content"
    return "position"


def _is_header_or_footer_span(
    bbox_pts: tuple[float, float, float, float] | dict[str, Any],
    page_height: float | None = None,
) -> bool:
    if isinstance(bbox_pts, dict):
        page_height = bbox_pts.get("page_height")
        raw_bbox = bbox_pts.get("bbox") or bbox_pts.get("bbox_pts")
        normalised_bbox = _normalise_bbox(raw_bbox)
        if normalised_bbox is None or page_height is None:
            return False
        bbox_pts = normalised_bbox

    if page_height is None:
        return False
    y_top = bbox_pts[1]
    y_bot = bbox_pts[3]
    return y_top < PDF_HEADER_MARGIN_PT or y_bot > (page_height - PDF_FOOTER_MARGIN_PT)


def _pdf_value_to_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _parse_pdf_date(value: str | None) -> datetime | None:
    if not value:
        return None

    match = PDF_DATE_RE.match(value.strip())
    if match is None:
        return None

    parts = match.groupdict()
    try:
        year = int(parts["year"])
        month = int(parts["month"] or "1")
        day = int(parts["day"] or "1")
        hour = int(parts["hour"] or "0")
        minute = int(parts["minute"] or "0")
        second = int(parts["second"] or "0")
        parsed = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None

    offset = parts.get("offset")
    if not offset:
        return parsed.replace(tzinfo=timezone.utc)
    if offset == "Z":
        return parsed.replace(tzinfo=timezone.utc)

    sign = 1 if offset[0] == "+" else -1
    digits = re.sub(r"\D", "", offset[1:])
    if len(digits) != 4:
        return parsed.replace(tzinfo=timezone.utc)
    offset_minutes = sign * (int(digits[:2]) * 60 + int(digits[2:]))
    return parsed.replace(tzinfo=timezone.utc) - timedelta(minutes=offset_minutes)


def _normalise_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if not bbox or len(bbox) != 4:
        return None
    try:
        return tuple(float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
