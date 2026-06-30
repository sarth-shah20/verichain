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

_CROSS_SYSTEM = """You are a consistency analyst for a bank's loan-underwriting
pipeline.

You receive the extracted fields from MULTIPLE documents submitted by ONE
applicant. Identify attributes that appear in more than one document (e.g. name,
address, PAN, date of birth, employer, income/salary, account number) and check
whether they agree.

Rules:
- Compare semantically (formatting, abbreviations, language differences are not
  conflicts). A genuine value difference IS a conflict.
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
    cross = llm_client.call_text(_CROSS_SYSTEM, _build_user_prompt(docs), json_mode=True)

    report: dict[str, Any] = {
        "report_type": "cross_document_discrepancy",
        "generated_at": utils.now_iso(),
        "document_count": len(reports),
        "documents": [d["label"] for d in docs],
        "cross_document": cross,
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
