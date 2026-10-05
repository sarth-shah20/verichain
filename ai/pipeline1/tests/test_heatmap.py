"""Offline tests for the heatmap + JPEG-ghost additions (no LLM, no network)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline1.pixel_forensics.block_grid import make_grid
from pipeline1.pixel_forensics.jpeg_ghost import run_jpeg_ghost
from pipeline1.schema import SuspectRegion
from pipeline1.tamper_map.heatmap import bbox_to_pct, generate_heatmap_pages


def _solid_image(h: int = 256, w: int = 256) -> np.ndarray:
    rng = np.random.default_rng(7)
    base = np.full((h, w, 3), 200, dtype=np.uint8)
    noise = rng.integers(-3, 4, size=(h, w, 3)).astype(np.int16)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def test_ghost_returns_block_scores():
    grid = make_grid(_solid_image())
    scores = run_jpeg_ghost(grid)
    assert len(scores) == len(grid.blocks)
    assert bool(np.all(np.isfinite(scores)))


def test_bbox_to_pct_math():
    pct = bbox_to_pct((50, 25, 100, 50), 200, 100)
    assert pct == {"x": 25.0, "y": 25.0, "w": 50.0, "h": 50.0}


def test_heatmap_renders_with_fake_regions(tmp_path):
    img = _solid_image(320, 240)
    p = tmp_path / "doc.png"
    import cv2

    cv2.imwrite(str(p), img)
    regions = [
        SuspectRegion(
            page_number=1,
            bbox=(10, 10, 60, 40),
            contributing_signals=["ela", "dct"],
            confidence="high",
            note="test box",
        )
    ]
    pages = generate_heatmap_pages(p, {0: regions})
    assert len(pages) == 1
    assert pages[0]["png_bytes"][:8] == b"\x89PNG\r\n\x1a\n"
    assert pages[0]["regions"][0]["bbox_pct"]["w"] > 0


def test_heatmap_empty_without_regions(tmp_path):
    img = _solid_image(128, 128)
    p = tmp_path / "blank.png"
    import cv2

    cv2.imwrite(str(p), img)
    pages = generate_heatmap_pages(p, {})
    # Heat tint still renders (useful as a "clean" baseline view); no boxes.
    assert len(pages) == 1
    assert pages[0]["regions"] == []
