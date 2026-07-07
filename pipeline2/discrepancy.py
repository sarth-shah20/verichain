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
    cross = llm_client.call_text(_CROSS_SYSTEM, _build_user_prompt(docs), json_mode=True)

    # Fold in deterministic identifier cross-checks (PAN consistency, GSTIN<->PAN).
    # These are high-confidence and must not be diluted by the LLM's judgement, so
    # we prepend them and force inconsistency when any deterministic conflict fires.
    det_cross = _deterministic_cross(docs)
    if det_cross:
        cross.setdefault("discrepancies", [])
        existing = cross["discrepancies"]
        cross["discrepancies"] = det_cross + (existing if isinstance(existing, list) else [])
        cross["entity_consistency"] = "inconsistent"

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
