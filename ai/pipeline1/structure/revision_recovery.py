"""
PDF revision recovery + before/after diff  —  the "killer" tamper artifact.

The most common soft-copy document fraud is an edit made in Acrobat or an online
PDF editor and saved as an INCREMENTAL UPDATE: the editor appends the changed
objects, a new cross-reference section and a new ``%%EOF`` to the end of the file
instead of rewriting it. The ORIGINAL bytes are still sitting inside the file.

This module reconstructs the prior revision by truncating the file at an earlier
``%%EOF`` boundary, reads the text of both the prior and the current revision,
and diffs them to recover the ORIGINAL value of any edited field — so the UI can
show "original: 37,000 -> edited: 96,000" exactly like Ocrolus's before/after
view. Changes are field-weighted (identifiers/amounts >> cosmetic text) so a
benign re-save that changed nothing does not raise risk.

Everything degrades gracefully: if PyMuPDF (``fitz``) is unavailable or a
revision cannot be parsed, we return an empty result with a warning rather than
raising.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from pipeline1.schema import RevisionChange, RevisionRecoveryResult

try:
    import fitz  # PyMuPDF
    _FITZ = True
except Exception:  # pragma: no cover - environment dependent
    _FITZ = False

_EOF = b"%%EOF"

# Token classifiers for field-weighting the recovered change.
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
_DATE_RE = re.compile(r"^(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})$")
_AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?$")


def _digit_tokens(tokens: list[str]) -> list[str]:
    return [t for t in tokens if any(c.isdigit() for c in t)]


def _clean(tok: str) -> str:
    return tok.strip().strip(".,:;()[]").strip()


def _classify(original: str, current: str) -> tuple[str, str]:
    """Return (kind, weight) for a recovered original->current change."""
    blob = f"{original} {current}".upper().replace(" ", "")
    o_c, c_c = _clean(original), _clean(current)

    if _PAN_RE.match(o_c.upper()) or _PAN_RE.match(c_c.upper()) or _GSTIN_RE.match(o_c.upper()):
        return "identifier", "high"
    # A long run of digits looks like an account / Aadhaar / reference number.
    digits_only = re.sub(r"\D", "", blob)
    if len(digits_only) >= 9 and not any(ch.isalpha() for ch in o_c):
        return "identifier", "high"
    if _DATE_RE.match(o_c) or _DATE_RE.match(c_c):
        return "date", "medium"
    if _AMOUNT_RE.match(o_c) or _AMOUNT_RE.match(c_c):
        return "amount", "high"
    if any(c.isdigit() for c in blob):
        return "amount", "high"
    # Pure text: a capitalised token is likely a name / proper noun.
    if o_c[:1].isupper() and c_c[:1].isupper() and len(o_c) > 1:
        return "name", "high"
    return "text", "low"


# --------------------------------------------------------------------------- #
# Byte-level revision slicing
# --------------------------------------------------------------------------- #

def _prior_revisions(raw: bytes) -> list[bytes]:
    """Byte prefixes of every revision that precedes the final one.

    Each incremental save ends with ``%%EOF``; the prefix up to any earlier
    ``%%EOF`` is a complete, self-contained earlier revision of the document.
    """
    ends: list[int] = []
    idx = 0
    while True:
        i = raw.find(_EOF, idx)
        if i == -1:
            break
        ends.append(i + len(_EOF))
        idx = i + len(_EOF)
    if len(ends) < 2:
        return []
    return [raw[:e] for e in ends[:-1]]


def _text_and_words(pdf_bytes: bytes) -> tuple[str, list[tuple[int, tuple[float, float, float, float], str]]]:
    """Return (full_text, words) for a PDF given as bytes.

    words: list of (page_number, bbox, text).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages_text: list[str] = []
        words: list[tuple[int, tuple[float, float, float, float], str]] = []
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            pages_text.append(page.get_text())
            for w in page.get_text("words"):
                bbox = (float(w[0]), float(w[1]), float(w[2]), float(w[3]))
                words.append((pno, bbox, str(w[4])))
        return "\n".join(pages_text), words
    finally:
        doc.close()


Word = tuple[int, tuple[float, float, float, float], str]


def _center(b: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _overlap_ratio(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection area as a fraction of the smaller box."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / min(area_a, area_b)


def _field_hint(bbox: tuple[float, float, float, float], page: int, words: list[Word]) -> str | None:
    """Best-effort field caption: words to the LEFT on the same text line."""
    y_mid = _center(bbox)[1]
    same_line = [
        t for (p, b, t) in words
        if p == page and abs(_center(b)[1] - y_mid) < 4.0 and b[0] < bbox[0] and _clean(t)
    ]
    return " ".join(same_line[-4:]).strip(" :\t") or None


def _diff_changes(
    before_words: list[Word],
    after_words: list[Word],
    before_text: str,
    after_text: str,
) -> list[RevisionChange]:
    """Recover edited field values by comparing the two revisions.

    Primary method is POSITION-BASED: an incremental "edit" typically covers the
    original value (white box) and writes a new value on top, so the current
    revision gains a word that OVERLAPS an original word at the same location.
    That overlap pins the recovered original next to the edited value. A
    text-sequence fallback catches edits that reflow the text instead.
    """
    changes: list[RevisionChange] = []

    # Words that are genuinely NEW in the current revision (same text at the same
    # place = unchanged, so excluded).
    before_by_text: dict[tuple[int, str], list[tuple[float, float, float, float]]] = {}
    for p, b, t in before_words:
        before_by_text.setdefault((p, _clean(t)), []).append(b)

    def unchanged(p: int, b: tuple[float, float, float, float], t: str) -> bool:
        for bb in before_by_text.get((p, _clean(t)), []):
            cx, cy = _center(b)
            ox, oy = _center(bb)
            if abs(cx - ox) < 4.0 and abs(cy - oy) < 4.0:
                return True
        return False

    used_original: set[int] = set()
    for p, b, t in after_words:
        if not _clean(t) or unchanged(p, b, t):
            continue
        # Find the original word this new word was written over.
        best_i, best_ov = -1, 0.0
        for i, (bp, bb, bt) in enumerate(before_words):
            if bp != p or i in used_original or _clean(bt) == _clean(t):
                continue
            ov = _overlap_ratio(b, bb)
            if ov > best_ov:
                best_ov, best_i = ov, i
        if best_i >= 0 and best_ov >= 0.25:
            used_original.add(best_i)
            original = before_words[best_i][2]
            kind, weight = _classify(original, t)
            changes.append(
                RevisionChange(
                    field_hint=_field_hint(b, p, after_words),
                    original_value=_clean(original),
                    current_value=_clean(t),
                    kind=kind,
                    weight=weight,
                    page_number=p,
                    bbox=b,
                )
            )

    if changes:
        return changes

    # Fallback: text-sequence diff (edits that reflow rather than overlay).
    before, after = before_text.split(), after_text.split()
    sm = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        b_seg, a_seg = before[i1:i2], after[j1:j2]
        b_nums, a_nums = _digit_tokens(b_seg), _digit_tokens(a_seg)
        pairs = (
            [(o, c) for o, c in zip(b_nums, a_nums) if _clean(o) != _clean(c)]
            if (b_nums or a_nums)
            else ([(" ".join(b_seg), " ".join(a_seg))] if b_seg and a_seg else [])
        )
        for original, current in pairs:
            if _clean(original) == _clean(current):
                continue
            kind, weight = _classify(original, current)
            changes.append(
                RevisionChange(
                    original_value=_clean(original),
                    current_value=_clean(current),
                    kind=kind,
                    weight=weight,
                )
            )
    return changes


def _render_first_page(pdf_bytes: bytes, out_path: Path, dpi: int = 120) -> str | None:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if doc.page_count == 0:
                return None
            pix = doc.load_page(0).get_pixmap(dpi=dpi)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(out_path))
            return str(out_path)
        finally:
            doc.close()
    except Exception:
        return None


def recover_revisions(
    path: str | Path,
    *,
    render: bool = False,
    out_dir: str | Path | None = None,
) -> RevisionRecoveryResult:
    """Recover the prior revision of an incrementally-saved PDF and diff it.

    Args:
        path:   the PDF on disk.
        render: if True, also rasterise the first page of both revisions.
        out_dir: where to write rendered images (defaults next to `path`).
    """
    result = RevisionRecoveryResult()
    file_path = Path(path)

    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        result.warnings.append(f"could not read PDF bytes: {exc}")
        return result

    result.revisions_found = max(0, raw.count(_EOF))
    priors = _prior_revisions(raw)
    result.incremental_update_detected = bool(priors)
    if not priors:
        return result

    if not _FITZ:
        result.warnings.append("PyMuPDF unavailable; recovered revisions but could not read text")
        return result

    try:
        current_text, current_words = _text_and_words(raw)
    except Exception as exc:
        result.warnings.append(f"could not read current revision text: {exc}")
        return result

    # Use the EARLIEST revision that parses and whose text/layout differs from
    # the current file — that is the original, pre-edit state.
    before_text: str | None = None
    before_words: list[Word] = []
    before_bytes = b""
    for prior in priors:
        try:
            text, words = _text_and_words(prior)
        except Exception:
            continue
        # Difference can be textual OR positional (overlay edits keep the same
        # words but add new ones), so compare word inventories, not just text.
        if words and (text.strip() != current_text.strip() or len(words) != len(current_words)):
            before_text, before_words, before_bytes = text, words, prior
            break

    if before_text is None:
        # Incremental update present but no textual change recovered: benign
        # re-save (or an image-only edit we can't read as text). NOT a flag.
        result.summary = (
            "PDF was incrementally re-saved, but no text change was recovered "
            "between revisions (likely a benign re-save)."
        )
        return result

    result.prior_revision_recovered = True
    result.recovered_changes = _diff_changes(
        before_words, current_words, before_text, current_text
    )

    if render:
        base = Path(out_dir) if out_dir else file_path.parent
        stem = file_path.stem
        result.original_render_path = _render_first_page(
            before_bytes, base / f"{stem}__revision_original.png"
        )
        result.current_render_path = _render_first_page(
            raw, base / f"{stem}__revision_current.png"
        )

    material = [c for c in result.recovered_changes if c.weight in ("high", "medium")]
    if material:
        top = material[0]
        label = f"{top.field_hint}: " if top.field_hint else ""
        result.summary = (
            f"Recovered a prior PDF revision — {label}original "
            f"'{top.original_value}' was edited to '{top.current_value}' "
            f"({len(material)} material change(s) recovered)."
        )
    else:
        result.summary = (
            "PDF was incrementally re-saved; recovered changes were cosmetic only."
        )
    return result


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: python revision_recovery.py <file.pdf> [--render]")
        raise SystemExit(1)
    res = recover_revisions(sys.argv[1], render="--render" in sys.argv)
    print(json.dumps(res.model_dump(), indent=2, default=str))
