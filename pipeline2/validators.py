"""
Deterministic (non-LLM) document validators.

These are *hard* checks that a fraudster who invents an identifier almost never
gets right, and that an LLM should never be trusted to compute reliably:

  - PAN   : format regex + 4th-char holder type + 5th char == surname initial
            (cross-checked against the name actually extracted from the document)
  - Aadhaar: Verhoeff checksum over all 12 digits
  - GSTIN : 15th-char (mod-36) checksum, state-code validity, and the embedded
            PAN (chars 3-12) — which downstream code cross-checks against the
            applicant's PAN from other documents

Design notes
------------
* Everything here is pure Python with no I/O, no LLM and no DB. It is cheap,
  deterministic and unit-testable, so it can run on every document and feed
  high-confidence evidence into verification and fusion.
* Findings use ONE common shape (`_finding`) so `verify.py`, `discrepancy.py`
  and the fusion layer can consume them uniformly.
* False-positive control is a project golden rule, so the checks are written to
  be conservative: a check whose inputs are missing/unreadable returns
  `passed=None` (informational) rather than a failure, and the surname check is
  lenient about Indian name ordering / honorifics before it flags anything.
"""

from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------- #
# Common finding shape
# --------------------------------------------------------------------------- #

# Severity for the frozen "field-weighted" hierarchy: identifier structure and
# checksum failures are strong, hard evidence of an invented/edited value.
Severity = str  # "info" | "low" | "medium" | "high"


def _finding(
    check: str,
    field: str,
    passed: bool | None,
    severity: Severity,
    detail: str,
    *,
    document_value: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    """Build one deterministic-check finding in the shared shape."""
    return {
        "check": check,
        "field": field,
        "document_value": document_value,
        "expected": expected,
        "passed": passed,
        "severity": severity,
        "detail": detail,
        "source": "deterministic_validator",
    }


# --------------------------------------------------------------------------- #
# PAN
# --------------------------------------------------------------------------- #

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# 4th character of a PAN encodes the holder type.
PAN_HOLDER_TYPES: dict[str, str] = {
    "P": "Individual",
    "C": "Company",
    "H": "Hindu Undivided Family (HUF)",
    "F": "Firm / LLP",
    "A": "Association of Persons (AOP)",
    "T": "Trust",
    "B": "Body of Individuals (BOI)",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "G": "Government",
}

# Honorifics / relationship markers that are NOT part of the legal name and must
# be ignored when deriving the surname initial for the 5th-char cross-check.
_NAME_NOISE = {
    "mr", "mrs", "ms", "m/s", "messrs", "dr", "shri", "sri", "smt", "kum",
    "s/o", "d/o", "w/o", "c/o", "son", "daughter", "wife", "of", "late",
}


def _name_tokens(name: str | None) -> list[str]:
    """Alphabetic name tokens, honorifics/relationship markers removed."""
    if not name:
        return []
    raw = re.split(r"[\s.,]+", str(name).strip())
    return [
        t for t in raw
        if t and t.lower() not in _NAME_NOISE and any(c.isalpha() for c in t)
    ]


def normalize_pan(pan: Any) -> str:
    return re.sub(r"\s+", "", str(pan or "")).upper()


def validate_pan(pan: Any, name: Any = None) -> list[dict[str, Any]]:
    """Validate a PAN's structure, holder type and surname-initial cross-check.

    The surname check is the discriminating one: for an individual PAN (4th char
    'P') the 5th character is the first letter of the holder's surname. Invented
    PANs almost never satisfy this against the name printed on the document.
    """
    findings: list[dict[str, Any]] = []
    value = normalize_pan(pan)
    if not value:
        return findings  # nothing extracted -> nothing to check

    # 1. Structure.
    structure_ok = bool(PAN_RE.match(value))
    findings.append(
        _finding(
            "pan_structure",
            "pan",
            structure_ok,
            "info" if structure_ok else "high",
            "PAN matches the AAAAA9999A pattern."
            if structure_ok
            else f"PAN '{value}' does not match the required AAAAA9999A pattern.",
            document_value=value,
            expected="AAAAA9999A",
        )
    )
    if not structure_ok:
        return findings  # further char checks are meaningless on a malformed PAN

    # 2. Holder-type (4th char).
    holder_char = value[3]
    holder_ok = holder_char in PAN_HOLDER_TYPES
    findings.append(
        _finding(
            "pan_holder_type",
            "pan",
            holder_ok,
            "info" if holder_ok else "high",
            f"4th char '{holder_char}' = {PAN_HOLDER_TYPES[holder_char]}."
            if holder_ok
            else f"4th char '{holder_char}' is not a valid PAN holder-type code.",
            document_value=holder_char,
            expected="one of " + "".join(sorted(PAN_HOLDER_TYPES)),
        )
    )

    # 3. Surname-initial cross-check (5th char).
    fifth = value[4]
    tokens = _name_tokens(name)
    if not tokens:
        findings.append(
            _finding(
                "pan_surname_initial",
                "pan",
                None,
                "info",
                f"5th char '{fifth}' could not be cross-checked — no name extracted.",
                document_value=fifth,
            )
        )
        return findings

    surname = tokens[-1]  # Indian convention: surname printed last
    surname_initial = surname[0].upper()
    initials = {t[0].upper() for t in tokens}

    if fifth == surname_initial:
        findings.append(
            _finding(
                "pan_surname_initial",
                "pan",
                True,
                "info",
                f"5th char '{fifth}' matches the surname initial ('{surname}').",
                document_value=fifth,
                expected=surname_initial,
            )
        )
    elif fifth in initials:
        # Matches a non-terminal name token — likely a name-order/transliteration
        # difference rather than fraud. Note it softly; do not raise a hard flag.
        findings.append(
            _finding(
                "pan_surname_initial",
                "pan",
                True,
                "low",
                f"5th char '{fifth}' matches a name component but not the last "
                f"token ('{surname}') — likely name-order variation, not fraud.",
                document_value=fifth,
                expected=surname_initial,
            )
        )
    else:
        findings.append(
            _finding(
                "pan_surname_initial",
                "pan",
                False,
                "high",
                f"5th char '{fifth}' does not match any name component "
                f"({', '.join(sorted(initials))}); surname '{surname}' implies "
                f"'{surname_initial}'. Strong signal of an invented/edited PAN.",
                document_value=fifth,
                expected=surname_initial,
            )
        )
    return findings


# --------------------------------------------------------------------------- #
# Aadhaar — Verhoeff checksum
# --------------------------------------------------------------------------- #

# Verhoeff dihedral-group multiplication table (D5).
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
# Permutation table.
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
# Inverse table.
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff_checksum(number: str) -> int:
    """Return the Verhoeff checksum of a digit string (0 == valid)."""
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(digit)]]
    return c


def verhoeff_check_digit(number: str) -> int:
    """Compute the Verhoeff check digit to append to `number`."""
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][int(digit)]]
    return _VERHOEFF_INV[c]


def verhoeff_validate(number: str) -> bool:
    return verhoeff_checksum(number) == 0


def normalize_aadhaar(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def validate_aadhaar(aadhaar: Any) -> list[dict[str, Any]]:
    """Verhoeff-checksum validation over all 12 Aadhaar digits."""
    findings: list[dict[str, Any]] = []
    digits = normalize_aadhaar(aadhaar)
    masked = f"XXXX-XXXX-{digits[-4:]}" if len(digits) >= 4 else "----"

    if len(digits) != 12:
        # Only the last 4 are available (privacy-masked) or the field is absent:
        # we cannot run Verhoeff. Not a failure — just unverifiable here.
        findings.append(
            _finding(
                "aadhaar_verhoeff",
                "aadhaar_number",
                None,
                "info",
                "Full 12-digit Aadhaar not available; Verhoeff checksum skipped.",
                document_value=masked,
            )
        )
        return findings

    ok = verhoeff_validate(digits)
    findings.append(
        _finding(
            "aadhaar_verhoeff",
            "aadhaar_number",
            ok,
            "info" if ok else "high",
            "Aadhaar passes the Verhoeff checksum."
            if ok
            else "Aadhaar FAILS the Verhoeff checksum — the number is invalid "
            "(fabricated or mistyped).",
            document_value=masked,
        )
    )
    return findings


# --------------------------------------------------------------------------- #
# GSTIN — checksum, state code, embedded PAN
# --------------------------------------------------------------------------- #

_GST_CODEPOINTS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Valid GST state / UT codes (01-38) plus special jurisdictions.
_GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "25": "Daman & Diu",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


def normalize_gstin(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def gstin_check_digit(first14: str) -> str:
    """GSTN mod-36 check-digit algorithm over the first 14 characters."""
    factor = 2
    total = 0
    for ch in reversed(first14):
        code = _GST_CODEPOINTS.index(ch)
        addend = factor * code
        addend = (addend // 36) + (addend % 36)
        total += addend
        factor = 1 if factor == 2 else 2
    return _GST_CODEPOINTS[(36 - (total % 36)) % 36]


def embedded_pan(gstin: Any) -> str:
    """The PAN embedded in a GSTIN (characters 3-12)."""
    value = normalize_gstin(gstin)
    return value[2:12] if len(value) >= 12 else ""


def validate_gstin(gstin: Any, applicant_pan: Any = None) -> list[dict[str, Any]]:
    """Validate GSTIN length/shape, state code, checksum and embedded PAN.

    If `applicant_pan` is supplied, the embedded PAN is cross-checked against it
    (a killer cross-document check: a GSTIN whose PAN is not the applicant's is a
    strong fraud/impersonation signal). Cross-doc callers may prefer to run that
    comparison in discrepancy.py where all documents are visible.
    """
    findings: list[dict[str, Any]] = []
    value = normalize_gstin(gstin)
    if not value:
        return findings

    if len(value) != 15:
        findings.append(
            _finding(
                "gstin_structure", "gstin", False, "high",
                f"GSTIN '{value}' is {len(value)} chars; a GSTIN is exactly 15.",
                document_value=value, expected="15 characters",
            )
        )
        return findings

    shape_ok = bool(GSTIN_RE.match(value))
    findings.append(
        _finding(
            "gstin_structure", "gstin", shape_ok,
            "info" if shape_ok else "high",
            "GSTIN matches the standard 15-char structure."
            if shape_ok
            else f"GSTIN '{value}' does not match the standard 15-char structure.",
            document_value=value,
        )
    )

    # State code (chars 1-2).
    state = value[:2]
    state_ok = state in _GST_STATE_CODES
    findings.append(
        _finding(
            "gstin_state_code", "gstin", state_ok,
            "info" if state_ok else "high",
            f"State code '{state}' = {_GST_STATE_CODES[state]}."
            if state_ok
            else f"State code '{state}' is not a valid GST state/UT code.",
            document_value=state,
        )
    )

    # Checksum (15th char).
    try:
        expected_cd = gstin_check_digit(value[:14])
        cd_ok = value[14] == expected_cd
    except ValueError:
        expected_cd = "?"
        cd_ok = False
    findings.append(
        _finding(
            "gstin_checksum", "gstin", cd_ok,
            "info" if cd_ok else "high",
            "GSTIN check digit is valid."
            if cd_ok
            else f"GSTIN check digit '{value[14]}' is wrong (expected "
            f"'{expected_cd}') — the GSTIN is invalid/fabricated.",
            document_value=value[14], expected=expected_cd,
        )
    )

    # Embedded PAN (chars 3-12): validate its own structure, then optionally
    # cross-check against the applicant's PAN.
    pan_in_gstin = embedded_pan(value)
    pan_structural = [
        f for f in validate_pan(pan_in_gstin)
        if f["check"] == "pan_structure"
    ]
    if pan_structural and pan_structural[0]["passed"] is False:
        findings.append(
            _finding(
                "gstin_embedded_pan", "gstin", False, "high",
                f"PAN embedded in the GSTIN ('{pan_in_gstin}') is not a valid PAN.",
                document_value=pan_in_gstin,
            )
        )

    if applicant_pan:
        want = normalize_pan(applicant_pan)
        match = pan_in_gstin == want
        findings.append(
            _finding(
                "gstin_embedded_pan", "gstin", match,
                "info" if match else "high",
                f"GSTIN's embedded PAN matches the applicant's PAN ({want})."
                if match
                else f"GSTIN's embedded PAN '{pan_in_gstin}' does NOT match the "
                f"applicant's PAN '{want}' — GSTIN belongs to a different entity.",
                document_value=pan_in_gstin, expected=want,
            )
        )
    return findings


# --------------------------------------------------------------------------- #
# Field extraction helpers + dispatcher
# --------------------------------------------------------------------------- #

def _first(fields: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if fields.get(k):
            return fields[k]
    return None


def extract_pan(fields: dict[str, Any]) -> str:
    return normalize_pan(_first(fields, "pan", "pan_number"))


def extract_gstin(fields: dict[str, Any]) -> str:
    return normalize_gstin(_first(fields, "gstin", "gst_number"))


def run_validators(doc_type: str | None, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Run every deterministic validator relevant to the extracted fields.

    Driven by which identifiers are actually present rather than only by
    doc_type, so an ITR/Form-16 that carries a PAN still gets PAN-validated.
    Returns a flat list of findings (possibly empty).
    """
    if not isinstance(fields, dict):
        return []
    findings: list[dict[str, Any]] = []

    name = _first(fields, "name", "employee_name", "assessee_name", "legal_name",
                  "account_holder", "owner_name")

    pan = extract_pan(fields)
    if pan:
        findings.extend(validate_pan(pan, name))

    aadhaar_full = _first(fields, "aadhaar_number", "aadhaar", "uid")
    if aadhaar_full:
        findings.extend(validate_aadhaar(aadhaar_full))

    gstin = extract_gstin(fields)
    if gstin:
        # Applicant-PAN cross-check is done in discrepancy.py (multi-doc view);
        # here we only self-validate the GSTIN. If the same doc also carries a
        # PAN, use it.
        findings.extend(validate_gstin(gstin, applicant_pan=pan or None))

    return findings


def worst_severity(findings: list[dict[str, Any]]) -> str:
    rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
    worst = "info"
    for f in findings:
        if f.get("passed") is False and rank.get(f.get("severity", "info"), 0) > rank[worst]:
            worst = f["severity"]
    return worst


def failures(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f.get("passed") is False]


# --------------------------------------------------------------------------- #
# Self-test (python validators.py)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import json

    print("PAN (valid, surname matches):")
    print(json.dumps(validate_pan("ABKPG7842M", "Mahadev Balu Gadade"), indent=2))

    print("\nPAN (5th char mismatches surname):")
    print(json.dumps(validate_pan("ABKPG7842M", "Ramesh Kumar Sharma"), indent=2))

    print("\nAadhaar (compute a valid one, then corrupt it):")
    base = "23412341234"
    good = base + str(verhoeff_check_digit(base))
    bad = base + ("0" if good[-1] != "0" else "1")
    print("  valid  ", good, verhoeff_validate(good))
    print("  invalid", bad, verhoeff_validate(bad))

    print("\nGSTIN (recompute the check digit for a sample):")
    sample = "27AAPFU0939F1Z"
    cd = gstin_check_digit(sample)
    print("  full:", sample + cd, "embedded PAN:", embedded_pan(sample + cd))
    print(json.dumps(validate_gstin(sample + cd, applicant_pan="AAPFU0939F"), indent=2))
