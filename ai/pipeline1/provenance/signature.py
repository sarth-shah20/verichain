"""Offline PDF digital-signature provenance checks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pikepdf
from pikepdf import Name, PasswordError

from pipeline1.schema import SignatureResult


def check_signature(path: str | Path) -> SignatureResult:
    """Inspect a PDF digital signature without making network calls.

    The result intentionally separates signed-byte integrity from certificate
    trust-chain validation. Self-signed and mock certificates are therefore
    reported as untrusted without being treated as digest/integrity failures.
    """

    file_path = Path(path)
    if not _looks_like_pdf(file_path):
        return SignatureResult(signature_present=False)

    try:
        file_size = file_path.stat().st_size
        with pikepdf.open(file_path) as pdf:
            signatures = _find_signature_payloads(pdf)
    except PasswordError as exc:
        return _unsigned_or_unreadable(f"PDF is encrypted or password-protected: {exc}")
    except (pikepdf.PdfError, OSError, ValueError) as exc:
        return _unsigned_or_unreadable(f"Malformed PDF; signature check could not parse it: {exc}")
    except Exception as exc:
        return _unsigned_or_unreadable(f"Unexpected PDF signature parsing error: {exc}")

    if not signatures:
        return _unsigned_or_unreadable("No embedded PDF signature found")

    last_signature = _last_signed_revision(signatures)
    last_byte_range = _byte_range(last_signature)
    signed_revision_length = _signed_revision_length(last_signature)
    modified_after_signing = (
        signed_revision_length is not None and signed_revision_length < file_size
    )

    warnings: list[str] = []
    if len(signatures) > 1:
        warnings.append(
            f"Multiple embedded signatures found; evaluated the last of {len(signatures)}"
        )
    if last_byte_range is None:
        warnings.append("Signature ByteRange is missing or malformed")
    elif signed_revision_length is None:
        warnings.append("Signature ByteRange could not be interpreted")
    elif modified_after_signing:
        warnings.append("PDF was modified after the last signature was applied")

    pyhanko_result = _validate_with_pyhanko(file_path)
    warnings.extend(pyhanko_result["warnings"])

    if pyhanko_result["modified_after_signing"] is not None:
        modified_after_signing = pyhanko_result["modified_after_signing"]

    return SignatureResult(
        signature_present=True,
        cryptographic_integrity_valid=pyhanko_result["cryptographic_integrity_valid"],
        trust_chain_valid=pyhanko_result["trust_chain_valid"],
        modified_after_signing=modified_after_signing,
        signer_name=pyhanko_result["signer_name"] or _signature_name(last_signature),
        signing_time=pyhanko_result["signing_time"] or _signature_time(last_signature),
        warnings=_dedupe(warnings),
        details={
            "signature_count": len(signatures),
            "signed_revision_length": signed_revision_length,
            "file_size": file_size,
        },
    )


def verify_signature(path: str | Path) -> SignatureResult:
    """Backward-compatible wrapper for older callers."""

    return check_signature(path)


def _validate_with_pyhanko(path: Path) -> dict[str, Any]:
    """Validate the last embedded signature with pyHanko, fully offline."""

    result: dict[str, Any] = {
        "cryptographic_integrity_valid": None,
        "trust_chain_valid": None,
        "modified_after_signing": None,
        "signer_name": None,
        "signing_time": None,
        "warnings": [],
    }

    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except Exception as exc:
        result["warnings"].append(f"pyHanko unavailable; signature integrity not validated: {exc}")
        return result

    try:
        validation_context = _offline_validation_context(ValidationContext)
        with path.open("rb") as document_file:
            reader = PdfFileReader(document_file)
            embedded_signatures = list(getattr(reader, "embedded_signatures", []))
            if not embedded_signatures:
                result["warnings"].append("pyHanko found no embedded signatures")
                return result

            embedded_signature = embedded_signatures[-1]
            status = validate_pdf_signature(
                embedded_signature,
                signer_validation_context=validation_context,
                ts_validation_context=validation_context,
            )

        result["cryptographic_integrity_valid"] = _status_bool(
            status,
            ("intact", "valid"),
        )
        result["trust_chain_valid"] = _status_bool(status, ("trusted",))
        result["modified_after_signing"] = _status_modified_after_signing(status)
        result["signer_name"] = _extract_pyhanko_signer_name(embedded_signature, status)
        result["signing_time"] = _extract_pyhanko_signing_time(embedded_signature, status)

        _append_status_warning(result["warnings"], status)
        if result["cryptographic_integrity_valid"] is False:
            result["warnings"].append("Signed byte ranges fail cryptographic integrity validation")
        if result["trust_chain_valid"] is False:
            result["warnings"].append("Signature certificate chain is not trusted locally")
    except Exception as exc:
        result["warnings"].append(f"pyHanko offline validation failed: {exc}")

    return result


def _offline_validation_context(validation_context_cls: Any) -> Any:
    """Construct a pyhanko-certvalidator context with fetching disabled."""

    try:
        return validation_context_cls(allow_fetching=False, revocation_mode="soft-fail")
    except TypeError:
        return validation_context_cls(allow_fetching=False)


def _looks_like_pdf(path: Path) -> bool:
    """Return whether the file should be treated as a PDF candidate."""

    if path.suffix.lower() == ".pdf":
        return True
    try:
        with path.open("rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def _find_signature_payloads(pdf: pikepdf.Pdf) -> list[Any]:
    """Return signature dictionaries from AcroForm fields."""

    acroform = _dict_get(pdf.Root, "/AcroForm")
    fields = _dict_get(acroform, "/Fields") if acroform is not None else None
    if fields is None:
        return []

    payloads: list[Any] = []
    for field in fields:
        payloads.extend(_signature_payloads_in_field(field))
    return payloads


def _signature_payloads_in_field(field: Any) -> list[Any]:
    """Recursively collect signature payload dictionaries from a form field."""

    payloads: list[Any] = []
    if _has_signature_payload(field):
        payloads.append(field)

    value = _dict_get(field, "/V")
    if value is not None and _has_signature_payload(value):
        payloads.append(value)

    kids = _dict_get(field, "/Kids")
    if kids is not None:
        for kid in kids:
            payloads.extend(_signature_payloads_in_field(kid))

    return payloads


def _has_signature_payload(value: Any) -> bool:
    """Return whether a PDF object contains signature payload keys."""

    return _dict_get(value, "/ByteRange") is not None and _dict_get(value, "/Contents") is not None


def _dict_get(mapping: Any, key: str) -> Any | None:
    """Safely read a PDF dictionary key from pikepdf objects."""

    try:
        return mapping.get(Name(key))
    except Exception:
        return None


def _last_signed_revision(signatures: list[Any]) -> Any:
    """Return the signature whose signed revision reaches farthest in the file."""

    return max(signatures, key=lambda signature: _signed_revision_length(signature) or -1)


def _byte_range(signature: Any) -> tuple[int, int, int, int] | None:
    """Return a normalised four-part PDF ByteRange."""

    byte_range = _dict_get(signature, "/ByteRange")
    if byte_range is None or len(byte_range) != 4:
        return None
    try:
        start, first_length, second_start, second_length = (
            int(value) for value in byte_range
        )
    except (TypeError, ValueError):
        return None
    if start != 0 or first_length < 0 or second_start < first_length or second_length < 0:
        return None
    return start, first_length, second_start, second_length


def _signed_revision_length(signature: Any) -> int | None:
    """Return the file offset reached by the signed revision."""

    byte_range = _byte_range(signature)
    if byte_range is None:
        return None
    return byte_range[2] + byte_range[3]


def _status_bool(status: Any, names: tuple[str, ...]) -> bool | None:
    """Extract a boolean-ish status attribute defensively."""

    for name in names:
        if hasattr(status, name):
            value = getattr(status, name)
            if value is None:
                continue
            return bool(value)
    return None


def _status_modified_after_signing(status: Any) -> bool | None:
    """Interpret pyHanko coverage status as a post-signing modification flag."""

    coverage = getattr(status, "coverage", None)
    if coverage is None:
        return None

    coverage_name = getattr(coverage, "name", str(coverage))
    if "ENTIRE_FILE" in coverage_name:
        return False
    if "ENTIRE_REVISION" in coverage_name or "CONTIGUOUS_BLOCK" in coverage_name:
        return True
    return None


def _append_status_warning(warnings: list[str], status: Any) -> None:
    """Append pyHanko's compact summary if it adds useful context."""

    summary = getattr(status, "summary", None)
    if callable(summary):
        try:
            summary_text = summary()
        except Exception:
            return
        if summary_text:
            warnings.append(f"pyHanko status: {summary_text}")


def _signature_name(signature: Any) -> str | None:
    """Extract signer name from the PDF signature dictionary."""

    return _string_value(_dict_get(signature, "/Name"))


def _signature_time(signature: Any) -> str | None:
    """Extract signing time from the PDF signature dictionary."""

    return _normalise_pdf_datetime(_string_value(_dict_get(signature, "/M")))


def _extract_pyhanko_signer_name(embedded_signature: Any, status: Any) -> str | None:
    """Extract signer name from pyHanko objects when available."""

    for source in (status, embedded_signature):
        for attr in ("signer_name", "signer_reported_name", "field_name"):
            value = getattr(source, attr, None)
            if value:
                return str(value)

    signing_cert = getattr(status, "signing_cert", None)
    subject = getattr(signing_cert, "subject", None)
    return str(subject) if subject is not None else None


def _extract_pyhanko_signing_time(embedded_signature: Any, status: Any) -> str | None:
    """Extract signing time from pyHanko objects when available."""

    for source in (status, embedded_signature):
        for attr in ("signing_time", "signer_reported_dt", "timestamp_validity"):
            normalised = _normalise_datetime_like(getattr(source, attr, None))
            if normalised is not None:
                return normalised
    return None


def _normalise_datetime_like(value: Any) -> str | None:
    """Return an ISO 8601 string for datetime-like values."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return _normalise_pdf_datetime(value)
    return None


def _normalise_pdf_datetime(value: str | None) -> str | None:
    """Convert a PDF date string to ISO 8601 where possible."""

    if not value:
        return None
    raw = value.removeprefix("D:")
    if len(raw) < 4:
        return value

    padded = raw[:14].ljust(14, "0")
    try:
        parsed = datetime.strptime(padded, "%Y%m%d%H%M%S")
    except ValueError:
        return value

    offset = raw[14:]
    if offset.startswith("Z"):
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _string_value(value: Any) -> str | None:
    """Convert pikepdf string-like objects to Python strings."""

    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _unsigned_or_unreadable(warning: str) -> SignatureResult:
    """Build a non-raising result for unsigned or malformed PDFs."""

    return SignatureResult(signature_present=False, warnings=[warning])


def _dedupe(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
