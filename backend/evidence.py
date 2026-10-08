"""Structured, inspectable evidence for the additive batch response."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def finding(source: str, code: str, label: str, detail: str, severity: str = "info", **extra) -> dict:
    key = json.dumps([source, code, detail, extra], sort_keys=True, default=str)
    return {"id": "ev_" + hashlib.sha256(key.encode()).hexdigest()[:12],
            "source": source, "check_code": code, "label": label, "detail": detail,
            "severity": severity, "document_ids": [], **extra}


def document_evidence(verification: dict, forensics: dict, holistic: dict) -> dict[str, Any]:
    ver = verification.get("verification", {})
    checks = ver.get("deterministic_checks", [])
    findings = []
    for check in checks:
        state = "passed" if check.get("passed") is True else "failed" if check.get("passed") is False else "skipped"
        findings.append(finding("content", check["check"], check["check"].replace("_", " ").title(),
            check.get("detail", ""), check.get("severity", "info"), state=state,
            field=check.get("field"), observed=check.get("document_value"), expected=check.get("expected"),
            page=check.get("page"), transaction_id=check.get("transaction_id")))
    for discrepancy in ver.get("discrepancies", []):
        if str(discrepancy.get("detail", "")).startswith("["):
            continue  # deterministic checks are already represented
        findings.append(finding("content", "reference_mismatch", "Reference record discrepancy",
            discrepancy.get("detail", ""), discrepancy.get("severity", "medium"), field=discrepancy.get("field")))
    for tier in forensics.get("tiers", []):
        recovery = (tier.get("evidence") or {}).get("revision_recovery", {})
        for change in recovery.get("recovered_changes", []):
            if change.get("weight") == "low":
                continue
            findings.append(finding("forensics", "revision_edit", "Original value recovered",
                f"{change.get('field_hint') or 'Field'}: {change.get('original_value')} → {change.get('current_value')}",
                "high" if change.get("weight") == "high" else "medium",
                observed=change.get("current_value"), expected=change.get("original_value"),
                page=change.get("page_number", 0) + 1))
    for region in forensics.get("suspect_regions", []):
        if region.get("confidence") == "low":
            continue
        findings.append(finding("forensics", "localized_signal", "Localized forensic signal",
            region.get("note", "") or ", ".join(region.get("signals", [])),
            "medium", page=region.get("page", 1), region=region.get("bbox_pct"), advisory=True))
    warnings = list(verification.get("analysis_warnings", []))
    if forensics.get("error"):
        warnings.append("File forensics could not complete.")
    if holistic.get("fusion", {}).get("fallback"):
        warnings.append("Risk fusion could not complete; evidence constraints and review defaults were applied.")
    for warning in warnings:
        findings.append(finding("analysis", "incomplete_stage", "Analysis incomplete", warning, "medium"))
    return {"findings": findings, "field_results": ver.get("field_results", []),
            "deterministic_checks": checks, "analysis_warnings": list(dict.fromkeys(warnings)),
            "analysis_status": "partial" if warnings else "complete",
            "content_status": ver.get("match_status", "unverified"),
            "forensics_summary": {"status": "unavailable" if forensics.get("error") else "checked",
                "material_edits": sum(f["check_code"] == "revision_edit" for f in findings),
                "advisory_regions": len(forensics.get("suspect_regions", [])),
                "signature_validation": "available" if any(
                    (t.get("evidence") or {}).get("signature", {}).get("cryptographic_integrity_valid") is not None
                    for t in forensics.get("tiers", [])) else "not_validated"}}
