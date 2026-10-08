import sys
from pathlib import Path
from unittest.mock import patch

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from routes.verify import _run_pipeline1, process_document


def test_second_page_edit_stays_on_second_page(tmp_path):
    p = tmp_path / "edit.pdf"
    d = fitz.open()
    for _ in range(2):
        d.new_page().insert_text((60, 100), "Synthetic salary statement. Gross Pay: 80,000", fontsize=11)
    d.save(p); d.close(); d = fitz.open(p)
    b = d[1].search_for("80,000")[0]
    d[1].draw_rect(b, color=(1, 1, 1), fill=(1, 1, 1))
    d[1].insert_text((b.x0, b.y1 - 2), "200000", fontsize=11)
    d.save(p, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP); d.close()
    result = _run_pipeline1(str(p))
    revisions = [r for r in result["suspect_regions"] if "revision_edit" in r["signals"]]
    assert revisions
    assert {r["page"] for r in revisions} == {2}


def test_extraction_outage_retains_forensic_edit(tmp_path):
    p = tmp_path / "input.pdf"
    d = fitz.open(); d.new_page().insert_text((50, 50), "Synthetic statement"); d.save(p); d.close()
    forensics = {"tiers": [{"evidence": {"revision_recovery": {"recovered_changes": [
        {"weight": "high", "original_value": "80000", "current_value": "200000"}]}}}]}
    with patch("routes.verify._run_pipeline1", return_value=forensics), \
         patch("pipeline.verify_document_file", side_effect=RuntimeError("outage")), \
         patch("llm_client.call_text", side_effect=RuntimeError("outage")):
        result = process_document(p.read_bytes(), "salary_slip")
    assert result["api"]["decision"] == "auto_reject"
    assert result["api"]["analysis_status"] == "partial"
    assert result["preview_pages"]
