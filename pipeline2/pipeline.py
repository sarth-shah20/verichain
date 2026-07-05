"""
Pipeline 2 orchestrator.

Input document  ->  [extract: VLM/OCR + normalize]  ->  [DB fetch]
                ->  [verify: separate session]      ->  verification report

The verification report is the artifact consumed downstream by:
  - discrepancy.py (cross-document consistency)
  - fusion.py      (merge with the forensics report -> overall risk score)
"""

from __future__ import annotations

import json
import os
from typing import Any

import db
import extract
import utils
import verify


def _readable_summary(report: dict[str, Any]) -> str:
    v = report["verification"]
    meta = report["document"]
    lines = [
        f"Document   : {meta['label']} ({meta['doc_type']})",
        f"Source file: {os.path.basename(meta['source_path'])}",
        f"DB record  : {'found' if report['database']['found'] else 'NOT FOUND (unverified)'}",
        f"Verdict    : {v.get('match_status', 'n/a').upper()}"
        f"  (confidence {v.get('verification_confidence', 'n/a')})",
        f"Summary    : {v.get('summary', '')}",
    ]
    discs = v.get("discrepancies", [])
    if discs:
        lines.append("Discrepancies:")
        for d in discs:
            lines.append(f"  - [{d.get('severity', '?').upper()}] {d.get('field')}: {d.get('detail')}")
    else:
        lines.append("Discrepancies: none")
    return "\n".join(lines)


def verify_document_file(
    path: str,
    doc_type: str | None = None,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """
    Run the full verification pipeline for one document.

    Returns the verification report (dict). If out_dir is given, also writes
    <name>.verification.json and <name>.verification.txt there.
    """
    # 1. Extract + normalize.
    extraction = extract.extract_document(path, doc_type)
    schema_meta = extraction["_schema"]

    # 2. Fetch authoritative record.
    db_response = db.fetch_record(
        schema_meta["db_collection"],
        schema_meta["key_fields"],
        extraction.get("fields", {}),
    )

    # 3. Verify (separate session).
    verification = verify.verify_document(extraction, db_response)

    # 4. Assemble the report.
    report: dict[str, Any] = {
        "report_type": "verification",
        "generated_at": utils.now_iso(),
        "document": {
            "doc_type": schema_meta["doc_type"],
            "label": schema_meta["label"],
            "source_path": path,
        },
        "extraction": {
            "fields": extraction.get("fields", {}),
            "full_text": extraction.get("full_text"),
            "language": extraction.get("language"),
            "normalization_notes": extraction.get("normalization_notes", []),
            "extraction_observations": extraction.get("extraction_observations", []),
            "unreadable_fields": extraction.get("unreadable_fields", []),
            "extraction_confidence": extraction.get("extraction_confidence"),
        },
        "database": db_response,
        "verification": verification,
    }
    report["summary_text"] = _readable_summary(report)

    if out_dir:
        base = os.path.splitext(os.path.basename(path))[0]
        utils.save_json(report, os.path.join(out_dir, f"{base}.verification.json"))
        with open(os.path.join(out_dir, f"{base}.verification.txt"), "w", encoding="utf-8") as fh:
            fh.write(report["summary_text"])

    return report


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python pipeline.py <file> [doc_type] [out_dir]")
        raise SystemExit(1)
    path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else None
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "reports"
    rep = verify_document_file(path, doc_type, out_dir)
    print(rep["summary_text"])
    print(f"\nJSON written to {out_dir}/")
