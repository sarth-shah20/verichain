"""Shared offline page rendering helpers."""

from __future__ import annotations

from pathlib import Path

import cv2
import fitz
import numpy as np

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
RENDER_ZOOM = 2.0


def get_page_images(path: str | Path) -> list[tuple[int, np.ndarray]]:
    """Return page images as BGR arrays without raising on malformed inputs."""

    file_path = Path(path)
    try:
        if file_path.suffix.lower() in IMAGE_EXTENSIONS:
            image = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
            return [] if image is None else [(0, image)]

        if file_path.suffix.lower() != ".pdf":
            return []

        images: list[tuple[int, np.ndarray]] = []
        with fitz.open(file_path) as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM),
                    alpha=False,
                )
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    pixmap.n,
                )
                if pixmap.n == 3:
                    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                images.append((page_index + 1, image))
        return images
    except Exception:
        return []
