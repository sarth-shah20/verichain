"""
End-to-end demo of Pipeline 2 + fusion, runnable with NO Vertex access.

Run:
    LLM_MOCK=1 python demo.py

It exercises every stage with the built-in mock LLM and writes all reports to
./reports/. With real credentials (LLM_MODEL + Vertex env set, LLM_MOCK unset)
the same code path runs against the live model -- just pass real files.
"""

from __future__ import annotations

import os

import discrepancy
import fusion
import pipeline
import utils

REPORTS = "reports"
SAMPLES = "samples"


def _ensure_sample_files() -> list[str]:
    """Create tiny placeholder image files so load_media has something to read.
    Content is irrelevant in mock mode (the mock LLM ignores pixels)."""
    os.makedirs(SAMPLES, exist_ok=True)
    files = []
    for name in ("itr.png", "address_proof.png"):
        p = os.path.join(SAMPLES, name)
        if not os.path.exists(p):
            # 1x1 PNG
            png = bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                "890000000a49444154789c6360000002000154a24f5d0000000049454e44ae42"
                "6082"
            )
            with open(p, "wb") as fh:
                fh.write(png)
        files.append(p)
    return files


def main() -> None:
    os.makedirs(REPORTS, exist_ok=True)
    itr_file, addr_file = _ensure_sample_files()

    print("=" * 70)
    print("STEP 1-3: Verify each document (extract -> DB -> verify)")
    print("=" * 70)
    rep_itr = pipeline.verify_document_file(itr_file, "salaried_itr", REPORTS)
    print(rep_itr["summary_text"], "\n")
    rep_addr = pipeline.verify_document_file(addr_file, "address_proof", REPORTS)
    print(rep_addr["summary_text"], "\n")

    print("=" * 70)
    print("STEP 4: Cross-document discrepancy check")
    print("=" * 70)
    cross = discrepancy.find_cross_document_discrepancies(
        [rep_itr, rep_addr], os.path.join(REPORTS, "cross_document.json")
    )
    print(cross["summary_text"], "\n")

    print("=" * 70)
    print("STEP 5: Fusion with forensics report -> holistic risk score")
    print("=" * 70)
    # Stand-in forensics report (Pipeline 1 produces the real one).
    forensics = {
        "report_type": "forensics",
        "document": "itr.png",
        "provenance": {"c2pa": "absent", "synthid": "not_detected", "qr_signature": "n/a"},
        "image_forensics": {
            "ela": "edited region detected near income field",
            "metadata": "creation tool: image editor; multiple save generations",
            "compression": "double-compression artifacts present",
        },
        "forensic_risk": "high",
    }
    flag_history = [
        {"flag": "round-number salary", "outcome": "false_positive", "times_seen": 4}
    ]
    holistic = fusion.fuse_reports(
        verification=[rep_itr, rep_addr],
        forensics=forensics,
        cross_doc=cross,
        flag_history=flag_history,
        out_path=os.path.join(REPORTS, "holistic.json"),
    )
    print(holistic["summary_text"], "\n")

    print(f"All reports written to ./{REPORTS}/")


if __name__ == "__main__":
    main()
