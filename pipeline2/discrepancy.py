"""
Cross-document discrepancy finder.

Takes the verification reports for several documents belonging to the SAME
applicant and checks whether the shared attributes (name, address, PAN, income,
employer, etc.) agree across documents. A single document can pass its own
verification yet still conflict with the rest of the file -- that is what this
catches.

Output: a consolidated discrepancy report (JSON + readable summary).
"""

from __future__ import annotations

import json
import os
from typing import Any

import llm_client
import utils
import validators

_CROSS_SYSTEM = """You are a consistency analyst for a bank's loan-underwriting
pipeline.

You receive the extracted fields from MULTIPLE documents submitted by ONE
applicant. Identify attributes that appear in more than one document (e.g. name,
address, PAN, date of birth, employer, income/salary, account number) and check
whether they agree.

Rules:
- Compare semantically (formatting, abbreviations, language differences are not
  conflicts). A genuine value difference IS a conflict.
- Only compare attributes where BOTH documents contain a concrete, non-null
  value. A missing/null value on one side is NOT a conflict — do NOT report it
  as a discrepancy (it belongs in consistent_attributes only if both have it,
  otherwise ignore it entirely).
- INCOME MUST BE NORMALIZED BEFORE COMPARISON. A salary slip states MONTHLY
  amounts while an ITR states ANNUAL amounts — never compare them raw.
  Annualize the slip (x12) or monthly-ize the ITR, then compare. A >15% gap
  between annualized payslip income and the ITR gross income needs review.
  Monthly x12 is an estimate, not proof of income understatement: employment
  periods, pay changes and tax years can differ. Rate this MEDIUM unless an
  independent reference-record discrepancy or material edit corroborates it.
- employer_name, address, etc.: missing vs present is not a conflict; two
  different present values are.
- Do not report the same attribute twice under different casings/spellings.
- For each conflict, list which documents disagree and the conflicting values.
- Rate severity low/medium/high (identity conflicts and large income conflicts
  are high; minor address-format differences are low/none).
- Also report which key attributes ARE consistent across documents.
- Return STRICT JSON only."""


def _collect_docs(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = []
    for r in reports:
        docs.append(
            {
                "doc_type": r.get("document", {}).get("doc_type", "unknown"),
                "label": r.get("document", {}).get("label", "Document"),
                "fields": r.get("extraction", {}).get("fields", {}),
                "own_verdict": r.get("verification", {}).get("match_status", "n/a"),
            }
        )
    return docs


def _deterministic_cross(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic cross-document identifier checks.

    Two killer checks an LLM should not be trusted to compute:
      1. PAN consistency — the same person's PAN must be identical across every
         document that carries one; two different valid PANs is an identity
         conflict.
      2. GSTIN <-> applicant PAN — a GSTIN embeds the holder's PAN in characters
         3-12. If the GSTIN on a business/tax document embeds a PAN that is not
         the applicant's PAN, the GST registration belongs to a different entity.
    """
    out: list[dict[str, Any]] = []

    # Collect (doc_type, PAN) pairs where a PAN was extracted.
    pans: list[tuple[str, str]] = []
    for d in docs:
        pan = validators.extract_pan(d.get("fields", {}))
        if pan:
            pans.append((d.get("doc_type", "document"), pan))

    distinct_pans = {p for _, p in pans}

    # 1. PAN must agree across documents.
    if len(distinct_pans) > 1:
        out.append(
            {
                "attribute": "PAN",
                "documents": [dt for dt, _ in pans],
                "values": [p for _, p in pans],
                "severity": "high",
                "detail": (
                    "Different PAN numbers appear across the applicant's "
                    "documents — the file may combine more than one identity."
                ),
            }
        )

    # The applicant's PAN: the single agreed PAN if documents are consistent.
    applicant_pan = next(iter(distinct_pans)) if len(distinct_pans) == 1 else None

    # 2. GSTIN embedded PAN must equal the applicant's PAN.
    for d in docs:
        gstin = validators.extract_gstin(d.get("fields", {}))
        if not gstin:
            continue
        emb = validators.embedded_pan(gstin)
        if not emb:
            continue
        # Compare against the applicant PAN if we have one, else against any
        # PAN present elsewhere in the file.
        target = applicant_pan or next(iter(distinct_pans), None)
        if target and emb != target:
            out.append(
                {
                    "attribute": "GSTIN / PAN",
                    "documents": [d.get("doc_type", "document")],
                    "values": [f"GSTIN PAN {emb}", f"applicant PAN {target}"],
                    "severity": "high",
                    "detail": (
                        "The PAN embedded in the GSTIN does not match the "
                        "applicant's PAN — the GST registration belongs to a "
                        "different entity (possible impersonation)."
                    ),
                }
            )
    # 3. Annualized-income consistency (LLM-free, cannot be talked out of it).
    out.extend(_income_cross_check(docs))
    for finding in out:
        finding["source"] = "deterministic"
        finding["definitive"] = finding["attribute"] in {"PAN", "GSTIN / PAN"}
        finding["check_code"] = {
            "PAN": "pan_consistency", "GSTIN / PAN": "gstin_pan_consistency",
        }.get(finding["attribute"], "income_estimate")

    return out


_MONTHLY_KEY_NAMES = ("gross_pay", "gross_salary", "gross_earnings", "basic_pay")
_ANNUAL_KEY_NAMES = ("gross_total_income", "annual_income", "total_income", "annual_gross_income")
_PAYSLIP_TYPES = ("salary", "payslip", "pay_slip", "salary_slip")
_ITR_TYPES = ("itr", "income_tax", "tax_return")


def _first_number(fields: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        for fk, fv in fields.items():
            if k in fk.lower() and isinstance(fv, (int, float)) and fv > 0:
                return float(fv)
    return None


def _income_cross_check(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag income understatement: annualize a monthly slip figure and compare
    it against the ITR's annual figure. >15% gap = HIGH (the classic
    loan-file fraud pattern), regardless of individual doc verdicts."""
    slip_annual: list[tuple[str, float]] = []
    itr_annual: list[tuple[str, float]] = []

    for d in docs:
        fields = d.get("fields", {}) or {}
        dt = (d.get("doc_type") or "").lower()
        monthly = _first_number(fields, _MONTHLY_KEY_NAMES)
        annual = _first_number(fields, _ANNUAL_KEY_NAMES)

        is_slip = any(t in dt for t in _PAYSLIP_TYPES) or (
            monthly is not None and fields.get("pay_period") is not None
        )
        is_itr = any(t in dt for t in _ITR_TYPES) or annual is not None

        if is_slip and monthly is not None:
            slip_annual.append((d.get("doc_type", "salary_slip"), monthly * 12.0))
        if is_itr and annual is not None:
            itr_annual.append((d.get("doc_type", "itr"), annual))

    out: list[dict[str, Any]] = []
    for slip_label, slip_year in slip_annual:
        for itr_label, itr_year in itr_annual:
            if slip_year <= 0 or itr_year <= 0:
                continue
            gap = abs(slip_year - itr_year) / max(slip_year, itr_year)
            if gap > 0.15:
                out.append(
                    {
                        "attribute": "income (annualized)",
                        "documents": [itr_label, slip_label],
                        "values": [
                            f"ITR gross {itr_year:,.0f}/yr",
                            f"salary slip {slip_year:,.0f}/yr (monthly x12)",
                        ],
                        "severity": "medium",
                        "detail": (
                            f"Annualized salary-slip income differs from the ITR's "
                            f"annual gross by {gap*100:.0f}%. Monthly ×12 is an estimate; "
                            "check employment and assessment periods before drawing a conclusion."
                        ),
                    }
                )
    return out


def _build_user_prompt(docs: list[dict[str, Any]]) -> str:
    return f"""Here are the documents submitted by one applicant:
{json.dumps(docs, indent=2, ensure_ascii=False)}

Cross-check shared attributes. Return JSON with this exact shape:
{{
  "entity_consistency": "consistent" | "inconsistent",
  "discrepancies": [
    {{
      "attribute": "<e.g. address>",
      "documents": ["<doc_type>", "<doc_type>"],
      "values": ["<value1>", "<value2>"],
      "severity": "low|medium|high",
      "detail": "<why this matters for underwriting>"
    }}
  ],
  "consistent_attributes": ["<attribute>", "..."],
  "summary": "<one-line plain-English verdict>"
}}"""


def _readable_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Cross-document check over {report['document_count']} documents: "
        f"{report['cross_document'].get('entity_consistency', 'n/a').upper()}",
        f"Documents: {', '.join(report['documents'])}",
    ]
    discs = report["cross_document"].get("discrepancies", [])
    if discs:
        lines.append("Conflicts:")
        for d in discs:
            docs = ", ".join(d.get("documents", []))
            vals = " vs ".join(str(v) for v in d.get("values", []))
            lines.append(f"  - [{d.get('severity', '?').upper()}] {d.get('attribute')} ({docs}): {vals}")
    else:
        lines.append("Conflicts: none")
    consistent = report["cross_document"].get("consistent_attributes", [])
    if consistent:
        lines.append(f"Consistent: {', '.join(consistent)}")
    return "\n".join(lines)


def find_cross_document_discrepancies(
    reports: list[dict[str, Any]],
    out_path: str | None = None,
) -> dict[str, Any]:
    """
    Args:
        reports: list of verification reports (dicts from pipeline.py).
        out_path: optional path to write the consolidated JSON.
    """
    if len(reports) < 2:
        raise ValueError("Need at least 2 verification reports to cross-check.")

    docs = _collect_docs(reports)
    det_cross = _deterministic_cross(docs)
    warnings: list[str] = []
    try:
        cross = llm_client.call_text(_CROSS_SYSTEM, _build_user_prompt(docs), json_mode=True)
        if not isinstance(cross, dict) or not isinstance(cross.get("discrepancies", []), list):
            raise ValueError("Invalid cross-document result")
    except Exception:
        warnings.append("AI cross-document analysis could not complete; deterministic checks are retained.")
        cross = {"entity_consistency": "unverified", "discrepancies": [],
                 "consistent_attributes": [], "summary": warnings[0]}

    # Fold in deterministic identifier cross-checks (PAN consistency, GSTIN<->PAN).
    # These are high-confidence and must not be diluted by the LLM's judgement, so
    # we prepend them and force inconsistency when any deterministic conflict fires.
    if det_cross:
        cross.setdefault("discrepancies", [])
        existing = cross["discrepancies"]
        cross["discrepancies"] = det_cross + (existing if isinstance(existing, list) else [])
        cross["entity_consistency"] = "inconsistent"

    unique: list[dict] = []
    seen: set[tuple] = set()
    for finding in cross.get("discrepancies", []):
        if not isinstance(finding, dict):
            continue
        attribute = str(finding.get("attribute", "")).lower()
        canonical = "income" if "income" in attribute else "pan" if attribute == "pan" else attribute
        key = (canonical, tuple(sorted(finding.get("documents", []))))
        if key not in seen:
            unique.append(finding)
            seen.add(key)
    cross["discrepancies"] = unique

    report: dict[str, Any] = {
        "report_type": "cross_document_discrepancy",
        "generated_at": utils.now_iso(),
        "document_count": len(reports),
        "documents": [d["label"] for d in docs],
        "cross_document": cross,
        "analysis_warnings": warnings,
    }
    report["summary_text"] = _readable_summary(report)

    if out_path:
        utils.save_json(report, out_path)
        with open(os.path.splitext(out_path)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(report["summary_text"])
    return report


def _load_reports(paths: list[str]) -> list[dict[str, Any]]:
    return [utils.load_json(p) for p in paths]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("usage: python discrepancy.py <report1.json> <report2.json> [...] ")
        print("       (writes reports/cross_document.json)")
        raise SystemExit(1)
    reports = _load_reports(sys.argv[1:])
    rep = find_cross_document_discrepancies(reports, "reports/cross_document.json")
    print(rep["summary_text"])
