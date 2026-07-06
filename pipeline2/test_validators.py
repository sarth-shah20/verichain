"""
Unit tests for the deterministic document validators.

Run:  cd pipeline2 && python -m pytest test_validators.py -q
   or: cd pipeline2 && python test_validators.py     (no pytest needed)
"""

from __future__ import annotations

import validators as v


def _by_check(findings, check):
    return next(f for f in findings if f["check"] == check)


# ------------------------------- PAN ---------------------------------------- #

def test_pan_valid_surname_match():
    f = v.validate_pan("ABKPG7842M", "Mahadev Balu Gadade")
    assert _by_check(f, "pan_structure")["passed"] is True
    assert _by_check(f, "pan_holder_type")["passed"] is True
    assert _by_check(f, "pan_surname_initial")["passed"] is True


def test_pan_bad_structure():
    f = v.validate_pan("ABCD1234XY", "Someone")
    assert _by_check(f, "pan_structure")["passed"] is False
    # no further checks once structure fails
    assert len(f) == 1


def test_pan_surname_mismatch_flags_high():
    f = v.validate_pan("ABKPG7842M", "Ramesh Kumar Sharma")  # surname 'S' != 'G'
    s = _by_check(f, "pan_surname_initial")
    assert s["passed"] is False and s["severity"] == "high"


def test_pan_surname_order_lenient():
    # 5th char 'G' matches a non-terminal token -> treated as benign name-order.
    f = v.validate_pan("ABKPG7842M", "Gadade Mahadev")
    s = _by_check(f, "pan_surname_initial")
    assert s["passed"] is True


def test_pan_no_name_is_informational():
    f = v.validate_pan("ABKPG7842M")
    s = _by_check(f, "pan_surname_initial")
    assert s["passed"] is None and s["severity"] == "info"


# ----------------------------- Aadhaar -------------------------------------- #

def test_verhoeff_valid_and_invalid():
    base = "23412341234"
    good = base + str(v.verhoeff_check_digit(base))
    assert v.verhoeff_validate(good) is True
    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    assert v.verhoeff_validate(bad) is False


def test_validate_aadhaar_full_number():
    base = "23412341234"
    good = base + str(v.verhoeff_check_digit(base))
    f = v.validate_aadhaar(good)
    assert _by_check(f, "aadhaar_verhoeff")["passed"] is True

    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    f2 = v.validate_aadhaar(bad)
    chk = _by_check(f2, "aadhaar_verhoeff")
    assert chk["passed"] is False and chk["severity"] == "high"


def test_validate_aadhaar_last4_only_is_unverifiable():
    f = v.validate_aadhaar("1234")
    assert _by_check(f, "aadhaar_verhoeff")["passed"] is None


# ------------------------------- GSTIN -------------------------------------- #

VALID_GSTIN = "27AAPFU0939F1ZV"  # state 27, PAN AAPFU0939F, valid checksum


def test_gstin_valid():
    f = v.validate_gstin(VALID_GSTIN)
    assert _by_check(f, "gstin_structure")["passed"] is True
    assert _by_check(f, "gstin_state_code")["passed"] is True
    assert _by_check(f, "gstin_checksum")["passed"] is True


def test_gstin_bad_checksum():
    broken = VALID_GSTIN[:-1] + ("A" if VALID_GSTIN[-1] != "A" else "B")
    f = v.validate_gstin(broken)
    c = _by_check(f, "gstin_checksum")
    assert c["passed"] is False and c["severity"] == "high"


def test_gstin_bad_state_code():
    # Build a real 15-char GSTIN with an invalid state code (88).
    body = "88AAPFU0939F1Z"
    full = body + v.gstin_check_digit(body)
    f = v.validate_gstin(full)
    assert _by_check(f, "gstin_state_code")["passed"] is False


def test_gstin_embedded_pan_match_and_mismatch():
    ok = v.validate_gstin(VALID_GSTIN, applicant_pan="AAPFU0939F")
    assert _by_check(ok, "gstin_embedded_pan")["passed"] is True

    bad = v.validate_gstin(VALID_GSTIN, applicant_pan="ABKPG7842M")
    m = _by_check(bad, "gstin_embedded_pan")
    assert m["passed"] is False and m["severity"] == "high"


def test_embedded_pan_extraction():
    assert v.embedded_pan(VALID_GSTIN) == "AAPFU0939F"


# --------------------------- Payslip arithmetic ------------------------------ #

def test_payslip_reconciles():
    f = v.validate_payslip_arithmetic(gross_pay=80000, deductions=10000, net_pay=70000)
    c = _by_check(f, "payslip_arithmetic")
    assert c["passed"] is True and c["severity"] == "info"


def test_payslip_arithmetic_tamper_detected():
    # Gross inflated (200000) while deductions/net were left untouched.
    f = v.validate_payslip_arithmetic(gross_pay=200000, deductions=10000, net_pay=70000)
    c = _by_check(f, "payslip_arithmetic")
    assert c["passed"] is False and c["severity"] == "high"
    assert c["expected"] == 190000.0


def test_payslip_arithmetic_tolerates_rounding():
    # Sub-rupee rounding must not false-positive.
    f = v.validate_payslip_arithmetic(gross_pay=80000, deductions=9999.6, net_pay=70000.4)
    assert _by_check(f, "payslip_arithmetic")["passed"] is True


def test_payslip_arithmetic_handles_currency_strings():
    f = v.validate_payslip_arithmetic(gross_pay="Rs. 80,000", deductions="10,000", net_pay="70,000")
    assert _by_check(f, "payslip_arithmetic")["passed"] is True


def test_payslip_arithmetic_skipped_when_incomplete():
    assert v.validate_payslip_arithmetic(gross_pay=80000, deductions=None, net_pay=70000) == []


def test_run_validators_dispatches_payslip_arithmetic():
    fields = {"gross_pay": 200000, "deductions": 10000, "net_pay": 70000}
    findings = v.run_validators("payslip", fields)
    c = _by_check(findings, "payslip_arithmetic")
    assert c["passed"] is False


# --------------------------- Dispatcher ------------------------------------- #

def test_run_validators_dispatches_by_present_fields():
    fields = {"pan": "ABKPG7842M", "name": "Mahadev Gadade", "gstin": VALID_GSTIN}
    findings = v.run_validators("gst_return", fields)
    checks = {f["check"] for f in findings}
    assert "pan_structure" in checks
    assert "gstin_checksum" in checks


def test_run_validators_empty_when_no_identifiers():
    assert v.run_validators("payslip", {"employee_name": "X", "gross_pay": 1000}) == []


# ------------------------------ Runner -------------------------------------- #
if __name__ == "__main__":
    import traceback

    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
