"""Small shared helpers: file discovery, PDF->images, JSON IO."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from llm_client import Media

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
PDF_EXTS = {".pdf"}
MAX_PDF_PAGES = 8
MAX_FILE_BYTES = 25 * 1024 * 1024


def inspect_input(data: bytes) -> str:
    """Validate the whole input before expensive/model processing."""
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("Files must be nonempty and no larger than 25 MB.")
    if data.startswith(b"%PDF-"):
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ValueError("Password-protected PDFs cannot be checked.")
            if not 1 <= doc.page_count <= MAX_PDF_PAGES:
                raise ValueError("PDFs must contain 1–8 pages. Split longer statements before uploading.")
        return ".pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif data.startswith(b"\xff\xd8"):
        suffix = ".jpg"
    else:
        raise ValueError("Unsupported file. Upload a PDF, JPG or PNG.")
    from PIL import Image
    import io
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    return suffix


@contextmanager
def document_media(path: str):
    """Own OCR render files for exactly the lifetime of the vision call."""
    with tempfile.TemporaryDirectory(prefix="verichain-ocr-") as directory:
        yield load_media(path, render_dir=directory)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_media(path: str, *, max_pdf_pages: int = MAX_PDF_PAGES, render_dir: str | None = None) -> list[Media]:
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
        return _pdf_to_media(path, max_pdf_pages, render_dir)
    raise ValueError(f"Unsupported input type: {ext}")


def _pdf_to_media(path: str, max_pages: int, render_dir: str | None = None) -> list[Media]:
    try:
        import fitz  # pymupdf
    except ImportError:
        # Send the PDF as-is; the multimodal model can handle application/pdf.
        return [Media(path)]

    out: list[Media] = []
    doc = fitz.open(path)
    if doc.page_count > max_pages:
        doc.close()
        raise ValueError(f"PDF exceeds the supported {max_pages} pages; no pages were submitted.")
    base = os.path.join(render_dir, "page") if render_dir else os.path.splitext(path)[0]
    for i, page in enumerate(doc):
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
