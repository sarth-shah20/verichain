"""Small shared helpers: file discovery, PDF->images, JSON IO."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from llm_client import Media

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
PDF_EXTS = {".pdf"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_media(path: str, *, max_pdf_pages: int = 8) -> list[Media]:
    """
    Turn an input file into a list of Media objects the vision model can read.

    - Images are passed straight through.
    - PDFs are rasterised page-by-page (needs pymupdf). If pymupdf is missing we
      fall back to sending the PDF bytes directly (the model can read PDFs), so
      the pipeline still works.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return [Media(path)]
    if ext in PDF_EXTS:
        return _pdf_to_media(path, max_pdf_pages)
    raise ValueError(f"Unsupported input type: {ext}")


def _pdf_to_media(path: str, max_pages: int) -> list[Media]:
    try:
        import fitz  # pymupdf
    except ImportError:
        # Send the PDF as-is; the multimodal model can handle application/pdf.
        return [Media(path)]

    out: list[Media] = []
    doc = fitz.open(path)
    base = os.path.splitext(path)[0]
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=200)
        img_path = f"{base}__page{i + 1}.png"
        pix.save(img_path)
        out.append(Media(img_path))
    doc.close()
    return out or [Media(path)]


def save_json(obj: Any, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
    return path


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
