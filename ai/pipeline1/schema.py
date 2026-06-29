"""Shared data models for Pipeline 1 document forensics."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    """Routing result for the authenticity and forensics pipeline."""

    document_type: Literal["signed_pdf", "born_digital_pdf", "scanned_image"]
    page_count: int
    has_embedded_signature: bool
    vector_text_ratio: float
    is_encrypted: bool
    warnings: list[str]


class SignatureResult(BaseModel):
    """Result of offline PDF signature provenance checks."""

    signature_present: bool
    cryptographic_integrity_valid: bool | None = None
    trust_chain_valid: bool | None = None
    modified_after_signing: bool | None = None
    signer_name: str | None = None
    signing_time: str | None = None
    warnings: list[str] = []
    details: dict | None = None

    @property
    def has_signature(self) -> bool:
        """Backward-compatible alias for earlier provenance code."""

        return self.signature_present

    @property
    def is_cryptographically_valid(self) -> bool | None:
        """Backward-compatible alias for the integrity verdict."""

        return self.cryptographic_integrity_valid

    @property
    def covers_whole_document(self) -> bool | None:
        """Backward-compatible inverse of post-signing modification status."""

        if self.modified_after_signing is None:
            return None
        return not self.modified_after_signing

    @property
    def reasons(self) -> list[str]:
        """Backward-compatible alias for warnings."""

        return self.warnings


class QRResult(BaseModel):
    """One decoded QR payload and where it was found."""

    payload: str
    page_number: int
    decoded_via_fallback: bool


class TierResult(BaseModel):
    """Combined tier output."""

    name: str
    authenticity_score: float
    reasons: list[str]
    evidence: dict | None = None
    confidence: Literal["high", "medium", "low"] = "high"


class FontSpanFinding(BaseModel):
    """One localized PDF font anomaly span in PDF point coordinates."""

    text: str
    font_name: str
    font_family_normalized: str
    bbox_pts: tuple[float, float, float, float]
    page_number: int


class PdfMetadataResult(BaseModel):
    """Born-digital PDF structure and embedded-font findings."""

    producer: str | None = None
    creator: str | None = None
    creation_date: str | None = None
    mod_date: str | None = None
    modification_delta_days: float | None = None
    modified_after_creation: bool = False
    startxref_count: int = 0
    incremental_update_detected: bool = False
    dominant_font: str | None = None
    font_family_mismatches: list[FontSpanFinding] = Field(default_factory=list)
    font_style_variants: list[FontSpanFinding] = Field(default_factory=list)
    header_footer_spans: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WordFinding(BaseModel):
    """One localized OCR typography finding in original image coordinates."""

    text: str
    page_number: int
    bbox_original: tuple[int, int, int, int]
    finding_type: Literal["typography_outlier", "baseline_misaligned"]
    signal_detail: str
    confidence: Literal["high", "low"]


class TypographyResult(BaseModel):
    """Visual typography findings from OCR word boxes on a raster page."""

    low_confidence: bool = False
    mean_ocr_confidence: float | None = None
    qualifying_line_count: int = 0
    typography_outlier_lines: list[dict[str, Any]] = Field(default_factory=list)
    baseline_misaligned_words: list[dict[str, Any]] = Field(default_factory=list)
    outlier_findings: list[WordFinding] = Field(default_factory=list)
    baseline_findings: list[WordFinding] = Field(default_factory=list)
    header_footer_lines: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExifResult(BaseModel):
    """Photo metadata findings from EXIF tags."""

    has_exif: bool = False
    software: str | None = None
    suspicious_software_detected: bool = False
    datetime_original_present: bool = False
    make: str | None = None
    model: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CopyMoveMatch(BaseModel):
    """One copy-move candidate pairing in original image coordinates."""

    source_bbox: tuple[int, int, int, int]
    target_bbox: tuple[int, int, int, int]
    page_number: int = 0
    similarity: float


class WatermarkMask(BaseModel):
    """Per-page repeated overlay mask on the same row/column grid as BlockGrid."""

    detected: bool = False
    coverage_fraction: float = 0.0
    dominant_angle_deg: float | None = None
    block_mask: list[list[bool]] = Field(default_factory=list)
    method: str = ""


class SuspectRegion(BaseModel):
    """Localized suspicious region in original image coordinates."""

    page_number: int
    bbox: tuple[int, int, int, int]
    contributing_signals: list[str]
    confidence: Literal["high", "medium", "low"]
    note: str


class PixelForensicsResult(BaseModel):
    """Tier 2 pixel-forensics localization output."""

    ela_ran: bool
    dct_ran: bool
    noise_ran: bool
    copy_move_ran: bool
    watermark_detected: bool = False
    watermark_coverage: float = 0.0
    suspect_regions: list[SuspectRegion]
    low_confidence: bool = False
    warnings: list[str] = Field(default_factory=list)


class QRCheckResult(BaseModel):
    """Legacy QR registry summary retained for older callers."""

    qr_found: bool
    payloads_decoded: list[str]
    registry_match: bool
    content_hash_match: bool
    reasons: list[str]


class ProvenanceResult(BaseModel):
    """Legacy Tier 0 combined output retained for older callers."""

    authenticity_score: float
    signature: SignatureResult
    qr_check: QRCheckResult
    reasons: list[str]
    evidence: dict | None = None
