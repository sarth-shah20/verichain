"""Tier 0 provenance orchestration for Pipeline 1."""

from __future__ import annotations

from pathlib import Path

from pipeline1.schema import ClassificationResult, QRResult, SignatureResult, TierResult

from . import mock_registry
from .qr import find_qr_codes
from .signature import check_signature

SIGNATURE_DOCUMENT_TYPES = {"signed_pdf", "born_digital_pdf"}


def run_tier0(path: str | Path, classification: ClassificationResult) -> TierResult:
    """Run offline provenance checks and combine them into one Tier result."""

    file_path = Path(path)
    reasons: list[str] = []
    score = 100.0

    file_hash = _safe_sha256(file_path, reasons)
    hash_record = mock_registry.lookup_by_hash(file_hash) if file_hash else None

    signature_result: SignatureResult | None = None
    if classification.document_type in SIGNATURE_DOCUMENT_TYPES:
        signature_result = check_signature(file_path)
        score = _apply_signature_result(
            score,
            reasons,
            signature_result,
            classification,
        )
    else:
        reasons.append(
            f"Signature check skipped for document type {classification.document_type}"
        )

    qr_results = find_qr_codes(file_path)
    score = _apply_qr_and_registry_results(
        score,
        reasons,
        qr_results,
        hash_record,
        file_hash,
    )

    if not qr_results and hash_record is None and not _signature_present(signature_result):
        reasons.append("No provenance markers found - expected for this document type")

    evidence = {
        "document_type": classification.document_type,
        "sha256": file_hash,
        "signature": signature_result.model_dump() if signature_result else None,
        "qr_codes": [result.model_dump() for result in qr_results],
        "registry_hash_match": hash_record.model_dump() if hash_record else None,
    }

    return TierResult(
        name="tier0_provenance",
        authenticity_score=max(0.0, min(100.0, score)),
        reasons=_dedupe(reasons),
        evidence=evidence,
    )


def _apply_signature_result(
    score: float,
    reasons: list[str],
    signature: SignatureResult,
    classification: ClassificationResult,
) -> float:
    """Update score and reasons from PDF signature evidence."""

    if not signature.signature_present:
        if classification.document_type == "signed_pdf":
            reasons.append("Classification expected a signature but none was verified")
            score -= 30.0
        else:
            reasons.append("No digital signature present; not required for this document type")
        reasons.extend(signature.warnings)
        return score

    reasons.append("Digital signature marker present")
    if signature.cryptographic_integrity_valid is True:
        reasons.append("Signed byte ranges are cryptographically intact")
    elif signature.cryptographic_integrity_valid is False:
        reasons.append("Signature present but signed byte ranges fail integrity validation")
        score -= 45.0
    else:
        reasons.append("Signature integrity could not be validated offline")

    if signature.modified_after_signing is True:
        reasons.append("Signature present but document modified after signing")
        score -= 35.0
    elif signature.modified_after_signing is False:
        reasons.append("No appended updates detected after the last signature")

    if signature.trust_chain_valid is True:
        reasons.append("Signature certificate chains to a locally trusted root")
    elif signature.trust_chain_valid is False:
        reasons.append("Signature trust chain is untrusted in the local offline context")
        score -= 10.0
    else:
        reasons.append("Signature trust chain was not established offline")

    reasons.extend(signature.warnings)
    return score


def _apply_qr_and_registry_results(
    score: float,
    reasons: list[str],
    qr_results: list[QRResult],
    hash_record: mock_registry.RegistryRecord | None,
    file_hash: str | None,
) -> float:
    """Update score and reasons from QR and local registry evidence."""

    if hash_record is not None:
        if hash_record.status == "known_fake":
            reasons.append("Document hash found in local registry as known_fake")
            return 0.0
        reasons.append("Document hash found in local registry as genuine")

    if not qr_results:
        reasons.append("No QR payloads found")
        return score

    qr_records = []
    for result in qr_results:
        record = mock_registry.lookup_by_qr_payload(result.payload)
        if record is None:
            reasons.append("QR payload not found in local registry")
            score -= 15.0
            continue
        qr_records.append(record)
        if record.status == "known_fake":
            reasons.append("QR payload found in local registry as known_fake")
            return 0.0
        reasons.append("QR payload found in local registry as genuine")
        if file_hash and record.doc_sha256.lower() != file_hash.lower():
            reasons.append("QR registry record found but document hash does not match")
            score -= 35.0
        elif file_hash:
            reasons.append("QR registry record hash matches this file")

    if qr_results and not qr_records:
        reasons.append("QR codes were decoded but none matched local registry records")

    return score


def _safe_sha256(path: Path, reasons: list[str]) -> str | None:
    """Compute a SHA-256 hash without letting file errors escape."""

    try:
        return mock_registry.sha256_of_file(path)
    except OSError as exc:
        reasons.append(f"Could not hash document for registry lookup: {exc}")
        return None


def _signature_present(signature: SignatureResult | None) -> bool:
    return bool(signature and signature.signature_present)


def _dedupe(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
