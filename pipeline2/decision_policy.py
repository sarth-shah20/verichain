"""Evidence constraints shared by document and application recommendations."""

from __future__ import annotations

from typing import Any

DEFINITIVE_CHECKS = {
    "pan_structure", "pan_holder_type", "aadhaar_verhoeff", "gstin_structure",
    "gstin_state_code", "gstin_checksum", "gstin_embedded_pan",
    "payslip_arithmetic", "statement_running_balance", "statement_totals",
}


def decide(score: int) -> tuple[str, str]:
    if score >= 80:
        return "route_1", "auto_approve"
    if score >= 60:
        return "route_2", "human_review"
    return "route_3", "auto_reject"


def constrain_score(
    score: int | None,
    verification: dict | list[dict],
    forensics: dict | list[dict] | None = None,
    cross_findings: list[dict] | None = None,
    *,
    incomplete: bool = False,
) -> tuple[int, list[str]]:
    """Never let model reassurance erase definitive evidence or missing analysis."""
    reports = verification if isinstance(verification, list) else [verification]
    forensic_reports = forensics if isinstance(forensics, list) else [forensics or {}]
    reasons: list[str] = []
    hard_evidence = False
    uncertain = incomplete or score is None
    for report in reports:
        ver = report.get("verification", {})
        uncertain |= ver.get("match_status", "unverified") == "unverified"
        uncertain |= bool(report.get("analysis_warnings"))
        for check in ver.get("deterministic_checks", []):
            if check.get("passed") is False and check.get("check") in DEFINITIVE_CHECKS:
                hard_evidence = True
                reasons.append(check.get("detail", "A definitive document check failed."))
        # A substantive discrepancy against a reference record is evidence too.
        if report.get("database", {}).get("found") and ver.get("match_status") in {"mismatch", "partial_match"}:
            severe = [d for d in ver.get("discrepancies", []) if d.get("severity") == "high"]
            if severe:
                hard_evidence = True
                reasons.extend(d.get("detail", "Material reference-record discrepancy.") for d in severe)
    for report in forensic_reports:
        uncertain |= bool(report.get("error"))
        for tier in report.get("tiers", []):
            recovery = (tier.get("evidence") or {}).get("revision_recovery", {})
            changes = recovery.get("recovered_changes", [])
            if any(c.get("weight") == "high" for c in changes):
                hard_evidence = True
                reasons.append(recovery.get("summary") or "A material value edit was recovered from the prior PDF revision.")
    for finding in cross_findings or []:
        if finding.get("severity") == "high" and finding.get("definitive"):
            hard_evidence = True
            reasons.append(finding.get("reason") or finding.get("detail") or "Identity conflict across documents.")
        elif finding.get("severity") in {"high", "medium"}:
            uncertain = True
    value = max(0, min(100, score if score is not None else 70))
    if hard_evidence:
        value = min(value, 40)
    elif uncertain:
        value = max(60, min(79, value))
    return value, list(dict.fromkeys(reasons))
