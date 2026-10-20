"""Forensic heatmap rendering for the document viewer.

Builds a per-page tamper heatmap PNG from the same block-score signals Tier 2
uses (ELA + DCT + noise + JPEG ghost), plus suspect-region boxes. Coordinates
are emitted both in pixels (server-side render) and percent (frontend overlay).

False-positive note: heatmaps visualize *anomaly intensity*, not verdicts. A
busy typed page (table grids, seals) lights up broadly — that is expected and
why Tier 2 stays advisory on e-records. Corroborated (high-confidence) boxes
are drawn distinctly from single-signal lows.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pipeline1.common.page_render import get_page_images
from pipeline1.pixel_forensics.block_grid import (
    BlockGrid,
    fused_zscore,
    make_grid,
)
from pipeline1.pixel_forensics.dct_blockmap import run_dct_anomaly
from pipeline1.pixel_forensics.ela import run_ela
from pipeline1.pixel_forensics.jpeg_ghost import run_jpeg_ghost
from pipeline1.pixel_forensics.noise_blockmap import run_noise_anomaly
from pipeline1.schema import SuspectRegion

MAX_HEATMAP_PAGES = 3
OVERLAY_ALPHA = 0.45

# BGR box colors: high = red, medium = amber, low = teal.
BOX_COLORS = {
    "high": (46, 46, 220),
    "medium": (18, 165, 245),
    "low": (20, 148, 13),
}


def fused_block_scores(grid: BlockGrid) -> np.ndarray:
    """Mean fused z-score across ELA/DCT/ghost (+ inverted noise). 0..n."""
    try:
        ela = np.asarray(run_ela(grid).get("block_scores", []), dtype=float)
        dct = np.asarray(run_dct_anomaly(grid), dtype=float)
        noise = np.asarray(run_noise_anomaly(grid), dtype=float)
        ghost = np.asarray(run_jpeg_ghost(grid), dtype=float)
        if not (ela.size == dct.size == noise.size == ghost.size) or ela.size == 0:
            return np.zeros(len(grid.blocks), dtype=float)
        fused = np.mean(
            [fused_zscore(ela), fused_zscore(dct), fused_zscore(ghost), -fused_zscore(noise)],
            axis=0,
        )
        return np.asarray(fused, dtype=float).reshape(-1)
    except Exception:
        return np.zeros(len(grid.blocks), dtype=float)


def render_page_heatmap(
    image_bgr: np.ndarray,
    grid: BlockGrid,
    scores: np.ndarray,
    regions: list[SuspectRegion],
) -> np.ndarray:
    """Blend a JET heat layer over the page and draw region boxes."""
    h, w = image_bgr.shape[:2]
    heat_full = np.zeros((h, w), dtype=np.float32)
    flat = np.asarray(scores, dtype=float).reshape(-1)
    # Normalize robustly: clip at p99 so one hot block doesn't wash the map.
    if flat.size:
        hi = float(np.percentile(np.maximum(flat, 0.0), 99)) or 1.0
        norm = np.clip(np.maximum(flat, 0.0) / max(hi, 1e-6), 0.0, 1.0)
    else:
        norm = np.zeros(len(grid.blocks), dtype=float)
    for block, v in zip(grid.blocks, norm, strict=False):
        # Map working-grid coords back to render resolution.
        sx = grid.scale_to_original
        # grid.blocks are in working coords; working==render here unless downscaled.
        # Paint in working space then resize: simpler to paint full-res via scaling.
        x0 = int(round(block.x * sx)) if sx != 1.0 else block.x
        y0 = int(round(block.y * sx)) if sx != 1.0 else block.y
        x1 = int(round((block.x + block.w) * sx)) if sx != 1.0 else block.x + block.w
        y1 = int(round((block.y + block.h) * sx)) if sx != 1.0 else block.y + block.h
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 > x0 and y1 > y0:
            heat_full[y0:y1, x0:x1] = float(v) * 255.0
    heat_full = cv2.GaussianBlur(heat_full, (0, 0), sigmaX=8)
    heat_color = cv2.applyColorMap(heat_full.astype(np.uint8), cv2.COLORMAP_JET)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    blended = cv2.addWeighted(gray_bgr, 1.0 - OVERLAY_ALPHA, heat_color, OVERLAY_ALPHA, 0)
    # Boxes on top.
    for r in regions:
        x, y, bw, bh = (int(v) for v in r.bbox)
        color = BOX_COLORS.get(r.confidence, BOX_COLORS["low"])
        thick = 3 if r.confidence == "high" else 2
        cv2.rectangle(blended, (x, y), (x + bw, y + bh), color, thick)
        label = f"{r.confidence}:{'+'.join(r.contributing_signals[:2])}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(blended, (x, max(0, y - th - 8)), (x + tw + 6, y), color, -1)
        cv2.putText(blended, label, (x + 3, max(th, y - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return blended


def bbox_to_pct(bbox: tuple[int, int, int, int], img_w: int, img_h: int) -> dict[str, float]:
    x, y, bw, bh = (float(v) for v in bbox)
    return {
        "x": round(100.0 * x / max(img_w, 1), 2),
        "y": round(100.0 * y / max(img_h, 1), 2),
        "w": round(100.0 * bw / max(img_w, 1), 2),
        "h": round(100.0 * bh / max(img_h, 1), 2),
    }


def generate_heatmap_pages(
    path: str | Path,
    regions_by_page: dict[int, list[SuspectRegion]] | None = None,
    max_pages: int = MAX_HEATMAP_PAGES,
) -> list[dict]:
    """Render heatmaps for the first N pages. Returns png_bytes + pct boxes."""
    pages = get_page_images(path)
    if not pages:
        return []
    out: list[dict] = []
    for page_number, image in pages[:max_pages]:
        try:
            grid = make_grid(image)
        except Exception:
            continue
        scores = fused_block_scores(grid)
        regions = (regions_by_page or {}).get(page_number, [])
        # Draw only high/medium boxes — lows stay visible as heat tint only,
        # otherwise a busy typed page is unreadable under dozens of boxes.
        boxed = [r for r in regions if r.confidence in ("high", "medium")]
        h0, w0 = image.shape[:2]
        rendered = render_page_heatmap(image, grid, scores, boxed)
        # Downscale for web serving (longest side ~1200px) to keep PNGs small.
        # Pct boxes are computed from the original dims so they stay correct.
        longest = max(rendered.shape[:2])
        if longest > 1200:
            scale = 1200.0 / float(longest)
            rendered = cv2.resize(rendered, (int(rendered.shape[1] * scale), int(rendered.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        ok, enc = cv2.imencode(".png", rendered)
        if not ok:
            continue
        out.append(
            {
                "page_number": page_number,
                "png_bytes": bytes(enc.tobytes()),
                "image_w": w0,
                "image_h": h0,
                "regions": [
                    {
                        "bbox_px": list(r.bbox),
                        "bbox_pct": bbox_to_pct(r.bbox, w0, h0),
                        "confidence": r.confidence,
                        "signals": list(r.contributing_signals),
                        "note": r.note,
                    }
                    for r in regions
                ],
            }
        )
    return out
