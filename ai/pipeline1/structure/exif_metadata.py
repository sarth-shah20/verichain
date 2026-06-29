"""Photo EXIF metadata checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline1.schema import ExifResult

SUSPICIOUS_SOFTWARE_MARKERS = ["photoshop", "gimp", "snapseed", "lightroom", "pixlr"]


def check_exif(path: str | Path) -> ExifResult:
    """Read informational EXIF fields and flag known editor software tags."""

    result = ExifResult()
    try:
        import piexif
    except ImportError as exc:
        result.warnings.append(f"piexif is not installed: {exc}")
        return result

    try:
        exif_data = piexif.load(str(path))
    except ValueError:
        return result
    except OSError as exc:
        result.warnings.append(f"could not read EXIF data: {exc}")
        return result
    except Exception as exc:
        result.warnings.append(f"EXIF parsing failed: {exc}")
        return result

    if not _has_any_exif(exif_data):
        return result

    result.has_exif = True
    result.software = _decode_exif_value(
        exif_data.get("0th", {}).get(piexif.ImageIFD.Software)
    )
    result.make = _decode_exif_value(exif_data.get("0th", {}).get(piexif.ImageIFD.Make))
    result.model = _decode_exif_value(exif_data.get("0th", {}).get(piexif.ImageIFD.Model))
    result.datetime_original_present = (
        exif_data.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal) is not None
    )

    software = (result.software or "").lower()
    result.suspicious_software_detected = any(
        marker in software for marker in SUSPICIOUS_SOFTWARE_MARKERS
    )
    return result


def _has_any_exif(exif_data: dict[str, Any]) -> bool:
    for ifd_name in ("0th", "Exif", "GPS", "1st"):
        values = exif_data.get(ifd_name)
        if isinstance(values, dict) and values:
            return True
    return bool(exif_data.get("thumbnail"))


def _decode_exif_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        for encoding in ("utf-8", "latin-1"):
            try:
                return value.decode(encoding).strip("\x00 ")
            except UnicodeDecodeError:
                continue
        return repr(value)
    return str(value).strip("\x00 ")
