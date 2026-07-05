"""
Unit test for PDF revision recovery (before/after diff).

Builds a real incremental-update PDF (original amount edited via overlay) and
asserts the original value is recovered. Skips if PyMuPDF is unavailable.

Run:  cd ai && PYTHONPATH=. python -m pytest pipeline1/structure/test_revision_recovery.py -q
   or: cd ai && PYTHONPATH=. python pipeline1/structure/test_revision_recovery.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

try:
    import fitz  # PyMuPDF
    _HAVE_FITZ = True
except Exception:
    _HAVE_FITZ = False

from pipeline1.structure.revision_recovery import recover_revisions


def _make_incremental_pdf(dirpath: Path) -> Path:
    """Original 'Basic Pay: 37,000' edited to '96,000' saved as an incremental update."""
    orig = dirpath / "orig.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 190), "Basic Pay: 37,000", fontsize=11)
    page.insert_text((72, 210), "Net Pay: 33,500", fontsize=11)
    doc.save(str(orig))
    doc.close()

    tampered = dirpath / "tampered.pdf"
    shutil.copyfile(orig, tampered)
    doc = fitz.open(str(tampered))
    page = doc.load_page(0)
    for r in page.search_for("37,000"):
        page.draw_rect(r, color=(1, 1, 1), fill=(1, 1, 1))
        page.insert_text((r.x0, r.y1 - 2), "96,000", fontsize=11)
    doc.save(str(tampered), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    return tampered


def test_recovers_edited_amount():
    if not _HAVE_FITZ:
        return  # environment without PyMuPDF -> skip
    with tempfile.TemporaryDirectory() as d:
        tampered = _make_incremental_pdf(Path(d))
        result = recover_revisions(tampered)

    assert result.incremental_update_detected is True
    assert result.prior_revision_recovered is True
    assert result.material_change_detected is True
    change = next(c for c in result.recovered_changes if c.weight == "high")
    assert change.original_value == "37,000"
    assert change.current_value == "96,000"


def test_single_revision_is_silent():
    if not _HAVE_FITZ:
        return
    with tempfile.TemporaryDirectory() as d:
        clean = Path(d) / "clean.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 100), "Basic Pay: 37,000", fontsize=11)
        doc.save(str(clean))
        doc.close()
        result = recover_revisions(clean)
    assert result.incremental_update_detected is False
    assert result.recovered_changes == []


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            ok += 1
        except Exception:
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{ok}/{len(tests)} passed")
    raise SystemExit(0 if ok == len(tests) else 1)
