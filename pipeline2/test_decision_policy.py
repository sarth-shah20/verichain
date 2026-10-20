from unittest.mock import patch

import pytest

from decision_policy import constrain_score, decide
from fusion import fuse_reports
from discrepancy import find_cross_document_discrepancies


def report(status="match", checks=None):
    return {"document": {"doc_type": "itr", "label": "ITR"},
            "database": {"found": status == "match"},
            "verification": {"match_status": status, "deterministic_checks": checks or []},
            "extraction": {"fields": {}}}


@pytest.mark.parametrize("score,decision", [(59, "auto_reject"), (60, "human_review"),
                                         (79, "human_review"), (80, "auto_approve")])
def test_thresholds(score, decision):
    assert decide(score)[1] == decision


def test_definitive_check_cannot_be_overruled():
    value, _ = constrain_score(100, report(checks=[{"check": "payslip_arithmetic", "passed": False}]))
    assert value == 40


def test_uncertainty_is_review_even_when_model_is_alarmist():
    assert constrain_score(0, report("unverified"))[0] == 60
    assert constrain_score(100, report("unverified"))[0] == 79


def test_fusion_outage_retains_revision_rejection():
    forensics = {"tiers": [{"evidence": {"revision_recovery": {
        "recovered_changes": [{"weight": "high"}], "summary": "Gross pay changed"}}}]}
    with patch("llm_client.call_text", side_effect=RuntimeError("outage")):
        result = fuse_reports(report(), forensics)
    value, reasons = constrain_score(100 - result["fusion"]["overall_risk_score"], report(),
                                     forensics, incomplete=result["fusion"]["fallback"])
    assert value == 40
    assert "Gross pay changed" in reasons


@pytest.mark.parametrize("risk", [-20, 101, "10", 0.5, True])
def test_invalid_fusion_output_requires_review(risk):
    with patch("llm_client.call_text", return_value={"overall_risk_score": risk}):
        result = fuse_reports(report(), {})
    assert result["fusion"]["fallback"] is True
    assert result["fusion"]["decision_recommendation"] == "manual_review"


def test_cross_outage_preserves_pan_conflict():
    reports = [report(), report()]
    for r, pan in zip(reports, ["ABCPD1234E", "XYZPK9876A"]):
        r["extraction"]["fields"]["pan"] = pan
    with patch("llm_client.call_text", side_effect=RuntimeError("outage")):
        result = find_cross_document_discrepancies(reports)
    assert result["analysis_warnings"]
    finding = result["cross_document"]["discrepancies"][0]
    assert finding["definitive"] is True
    assert constrain_score(95, [], cross_findings=[finding])[0] == 40
