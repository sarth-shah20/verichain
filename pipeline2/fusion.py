"""
Fusion / holistic report.

Merges the two pipeline outputs into one underwriting verdict:
  - the VERIFICATION report  (Pipeline 2: content extraction + DB check)
  - the FORENSICS report     (Pipeline 1: authenticity & image/file forensics)

Optionally also folds in:
  - a cross-document discrepancy report (discrepancy.py)
  - flag history (past false flags) so we don't repeatedly penalise benign quirks

Output: a holistic report with an overall risk score (0-100), a risk band, a
decision recommendation, and the specific flagged evidence behind the score.
"""

from __future__ import annotations

import json
import os
from typing import Any

import llm_client
import utils

_FUSION_SYSTEM = """You are the senior risk-fusion engine for a bank's loan
underwriting.

You receive independent reports about the SAME application:
- a content-verification report (does the document's data match the bank's
  records?),
- a forensics report (is the document file/image authentic, or edited/AI-made?),
- optionally a cross-document consistency report,
- optionally a flag-history list of previously confirmed FALSE flags.

Produce ONE holistic risk assessment.

Scoring guidance (0 = clean, 100 = almost certainly fraudulent):
- CROSS-PIPELINE corroboration is what matters most: raise the score sharply ONLY
  when the CONTENT check and the FORENSICS check point at the SAME tampering (e.g.
  a field whose value mismatches the bank's record AND shows pixel edits in that
  region). Two forensic sub-methods agreeing (copy-move + DCT + ELA) is NOT
  cross-pipeline corroboration on its own.
- CRITICAL false-positive control: typed / scanned government e-records (7/12, RTC,
  patta-chitta, ITRs, payslips) routinely trigger copy-move / DCT / ELA pixel
  "manipulation" signals on their repeated text, table grids, seals and uniform
  fills — even a low forensic authenticity score is common and benign on these.
  When the CONTENT verification MATCHES the authoritative record (especially a
  unique-ID / ULPIN / PAN / account-number match) and reports NO substantive
  discrepancy, treat a lone forensic pixel-anomaly as LOW confidence. Do NOT
  recommend "decline" on an uncorroborated forensic signal alone — cap such cases
  at "manual_review" (keep the score below 60).
- A high-severity CONTENT mismatch against the authoritative record is serious on
  its own.
- DETERMINISTIC checks are HARD evidence, not judgement calls — this includes both
  identifier checks AND arithmetic-reconciliation checks. A failed PAN structure/
  holder-type check, a failed Aadhaar Verhoeff checksum, a failed GSTIN checksum/
  state-code check, a GSTIN whose embedded PAN is not the applicant's PAN, or a
  payslip whose gross pay minus deductions does not equal its stated net pay,
  means the value is fabricated/edited — treat these as HIGH weight and raise the
  score sharply even without a pixel signal, and EVEN WHEN the document has no
  DB-of-record match (a payslip has no issuer database by design; the arithmetic
  check IS its verification). (These arrive in the verification report's
  "deterministic_checks" and as discrepancies tagged with the check name in
  brackets.)
- FIELD-WEIGHTED risk: weight WHICH field was edited/mismatched, mirroring how a
  human underwriter reads fraud. In descending order of severity:
    1. Identity & money fields — name, PAN, Aadhaar, account number, GSTIN,
       income/salary/amount, and any recovered "original -> edited" value on such
       a field. An edit or mismatch here is a top_flag at HIGH weight.
    2. Structural/authority fields — dates, issuer, survey/parcel numbers,
       employer, acknowledgement numbers: MEDIUM weight.
    3. Cosmetic/description fields — descriptions, labels, formatting, layout
       text, benign re-saves with no value change: LOW weight, usually not a flag.
  Never let a cosmetic-field edit outrank an identity/amount edit.
- "unverified" (no DB record) is uncertainty, not proof of fraud -> moderate.
- If a flag matches a known prior FALSE flag, down-weight it and note the
  adjustment.
- Do NOT raise risk for informational/portal watermarks such as "for viewing
  only", "not for legal purpose", or "informational copy". These are normal on
  legitimately downloaded government e-record copies and are NOT fraud evidence.
Bands: 0-29 low, 30-59 medium, 60-100 high.
Recommendations: "approve" | "manual_review" | "decline".

Be CONCISE so the JSON is never truncated: at most 4 top_flags, each "evidence"
a single short sentence. Keep "rationale" to one or two sentences.
Return STRICT JSON only. Cite concrete evidence from the inputs -- do not invent."""


def _slim_verification(v: dict[str, Any]) -> dict[str, Any]:
    ver = v.get("verification", {})
    # Only the FAILED deterministic checks matter to fusion; passing ones are noise.
    det_failures = [
        c for c in ver.get("deterministic_checks", []) if c.get("passed") is False
    ]
    return {
        "document": v.get("document", {}),
        "match_status": ver.get("match_status"),
        "discrepancies": ver.get("discrepancies", []),
        "deterministic_check_failures": det_failures,
        "extraction_observations": v.get("extraction", {}).get("extraction_observations", []),
        "db_found": v.get("database", {}).get("found"),
    }


def _build_user_prompt(
    verification: dict[str, Any] | list[dict[str, Any]],
    forensics: dict[str, Any],
    cross_doc: dict[str, Any] | None,
    flag_history: list[dict[str, Any]] | None,
) -> str:
    if isinstance(verification, list):
        ver_payload = [_slim_verification(v) for v in verification]
    else:
        ver_payload = _slim_verification(verification)

    parts = [
        "VERIFICATION REPORT(S):",
        json.dumps(ver_payload, indent=2, ensure_ascii=False),
        "",
        "FORENSICS REPORT:",
        json.dumps(forensics, indent=2, ensure_ascii=False),
    ]
    if cross_doc is not None:
        parts += ["", "CROSS-DOCUMENT REPORT:", json.dumps(cross_doc.get("cross_document", cross_doc), indent=2, ensure_ascii=False)]
    if flag_history:
        parts += ["", "FLAG HISTORY (known prior FALSE flags):", json.dumps(flag_history, indent=2, ensure_ascii=False)]

    parts += [
        "",
        """Return JSON with this exact shape:
{
  "overall_risk_score": <0-100 integer>,
  "risk_band": "low" | "medium" | "high",
  "decision_recommendation": "approve" | "manual_review" | "decline",
  "top_flags": [
    { "source": "verification|forensics|cross_document",
      "evidence": "<concrete finding>",
      "weight": "low|medium|high" }
  ],
  "corroborated_findings": [ "<findings flagged by more than one source>" ],
  "false_flag_adjustments": [ "<flags down-weighted due to flag history>" ],
  "rationale": "<2-4 sentence explanation of the score and recommendation>"
}""",
    ]
    return "\n".join(parts)


def _readable_summary(report: dict[str, Any]) -> str:
    h = report["fusion"]
    lines = [
        f"OVERALL RISK SCORE : {h.get('overall_risk_score')}/100  ({h.get('risk_band', '?').upper()})",
        f"RECOMMENDATION     : {h.get('decision_recommendation', 'n/a').upper()}",
        "",
        "Top flags:",
    ]
    for f in h.get("top_flags", []):
        lines.append(f"  - [{f.get('weight', '?').upper()}] ({f.get('source')}) {f.get('evidence')}")
    if h.get("corroborated_findings"):
        lines.append("Corroborated by multiple sources:")
        for c in h["corroborated_findings"]:
            lines.append(f"  - {c}")
    if h.get("false_flag_adjustments"):
        lines.append("Down-weighted (prior false flags):")
        for a in h["false_flag_adjustments"]:
            lines.append(f"  - {a}")
    lines += ["", f"Rationale: {h.get('rationale', '')}"]
    return "\n".join(lines)


def _worst_match_status(
    verification: dict[str, Any] | list[dict[str, Any]],
) -> str:
    """Return the most concerning match_status across one or more reports."""
    reports = verification if isinstance(verification, list) else [verification]
    rank = {"mismatch": 3, "partial_match": 2, "unverified": 1, "match": 0}
    worst = "match"
    for r in reports:
        ms = (r or {}).get("verification", {}).get("match_status", "unverified")
        if rank.get(ms, 1) > rank.get(worst, 0):
            worst = ms
    return worst


def _fallback_fusion(
    verification: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Heuristic verdict used when the fusion LLM output can't be parsed.

    A malformed/truncated LLM response must not throw away a verification that
    already succeeded, so we derive a sensible risk verdict from the content
    match_status (mirrors the mock-fusion convention: 0 = clean, 100 = fraud).
    """
    ms = _worst_match_status(verification)
    if ms == "match":
        risk, band, rec = 10, "low", "approve"
        evidence = "All checked fields match the authoritative DB record."
    elif ms == "mismatch":
        risk, band, rec = 82, "high", "decline"
        evidence = "Critical field mismatch vs the authoritative DB record."
    else:  # unverified / partial_match
        risk, band, rec = 35, "medium", "manual_review"
        evidence = "Document could not be fully verified against an authoritative record."
    return {
        "overall_risk_score": risk,
        "risk_band": band,
        "decision_recommendation": rec,
        "top_flags": [{"source": "verification", "evidence": evidence, "weight": "medium"}],
        "corroborated_findings": [],
        "false_flag_adjustments": [],
        "rationale": (
            "Fusion LLM output could not be parsed; verdict derived from the "
            f"content verification match_status ({ms})."
        ),
        "fallback": True,
    }


def fuse_reports(
    verification: dict[str, Any] | list[dict[str, Any]],
    forensics: dict[str, Any],
    cross_doc: dict[str, Any] | None = None,
    flag_history: list[dict[str, Any]] | None = None,
    out_path: str | None = None,
) -> dict[str, Any]:
    """
    Merge verification + forensics (+ optional cross-doc + flag history) into a
    holistic risk report.

    Args:
        verification: one verification report or a list of them.
        forensics: the Pipeline 1 forensics report (any JSON structure).
        cross_doc: optional cross-document discrepancy report.
        flag_history: optional list of known prior false flags.
        out_path: optional path to write the holistic JSON.
    """
    try:
        fusion = llm_client.call_text(
            _FUSION_SYSTEM,
            _build_user_prompt(verification, forensics, cross_doc, flag_history),
            json_mode=True,
        )
    except Exception:
        # A malformed/truncated LLM response must not sink a document whose
        # content verification already succeeded — degrade to a heuristic verdict.
        fusion = _fallback_fusion(verification)

    report: dict[str, Any] = {
        "report_type": "holistic_risk",
        "generated_at": utils.now_iso(),
        "inputs": {
            "verification_reports": len(verification) if isinstance(verification, list) else 1,
            "forensics_report": True,
            "cross_document_report": cross_doc is not None,
            "flag_history_entries": len(flag_history) if flag_history else 0,
        },
        "fusion": fusion,
    }
    report["summary_text"] = _readable_summary(report)

    if out_path:
        utils.save_json(report, out_path)
        with open(os.path.splitext(out_path)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(report["summary_text"])
    return report


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("usage: python fusion.py <verification.json> <forensics.json> [cross_doc.json] [flag_history.json]")
        raise SystemExit(1)
    ver = utils.load_json(sys.argv[1])
    fore = utils.load_json(sys.argv[2])
    cross = utils.load_json(sys.argv[3]) if len(sys.argv) > 3 else None
    flags = utils.load_json(sys.argv[4]) if len(sys.argv) > 4 else None
    rep = fuse_reports(ver, fore, cross, flags, "reports/holistic.json")
    print(rep["summary_text"])
