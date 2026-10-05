import { useState } from "react";
import { Eye, EyeOff, ImageOff } from "lucide-react";
import type { DocumentResult, Region, Severity } from "@/api/types";
import { cx } from "@/lib/format";

interface RegionMarker {
  id: string;
  region: Region;
  label: string;
  pipeline: 1 | 2;
  severity: Severity;
}

const SEVERITY_COLOR: Record<Severity, string> = {
  high: "#dc2626",
  medium: "#f59e0b",
  low: "#0d9488",
  info: "#64748b",
};

interface DocumentViewerProps {
  doc: DocumentResult;
  /** Currently highlighted region id (e.g. clicked from a signal). */
  activeRegionId?: string | null;
  onRegionClick?: (id: string) => void;
  /** Override the heatmap source (e.g. a selected page thumb). */
  heatmapUrlOverride?: string | null;
}

/**
 * Shows the document (heatmap if available, else thumbnail) and draws labelled
 * boxes for every signal that carries a region. Regions are percentages (0–100)
 * of the image box, so they scale responsively. Overlay can be toggled off.
 */
export function DocumentViewer({
  doc,
  activeRegionId,
  onRegionClick,
  heatmapUrlOverride,
}: DocumentViewerProps) {
  const [showOverlay, setShowOverlay] = useState(true);
  const [showHeatmap, setShowHeatmap] = useState(true);

  const heatmapUrl = heatmapUrlOverride !== undefined ? heatmapUrlOverride : (doc.pipeline1.heatmap_url ?? null);
  // A PDF upload renders in an embedded viewer; images (and forensic heatmaps)
  // render as a bitmap with clickable region overlays. The heatmap takes
  // precedence when present — it IS the document view with tamper intensity
  // baked in, plus the box overlay below.
  const isPdf = /\.pdf$/i.test(doc.filename);
  const pdfSrc = isPdf ? (doc.preview_url ?? null) : null;
  const originalSrc = isPdf ? null : (doc.preview_url ?? doc.thumbnail_url);
  const imageSrc = showHeatmap && heatmapUrl ? heatmapUrl : originalSrc;
  // Show the iframe only when there is no heatmap to display (or the user
  // toggled back to the original document and it is a PDF).
  const showIframe = !imageSrc && !!pdfSrc;
  const markers = collectRegions(doc);

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Document {heatmapUrl ? (showHeatmap ? "· heatmap" : "· original") : "preview"}
        </h3>
        <div className="flex items-center gap-2">
          {heatmapUrl && (pdfSrc || originalSrc) && (
            <button
              onClick={() => setShowHeatmap((v) => !v)}
              className="btn-ghost px-2 py-1 text-xs"
              aria-pressed={showHeatmap}
            >
              {showHeatmap ? "View original" : "View heatmap"}
            </button>
          )}
          {markers.length > 0 && imageSrc && (
            <button
              onClick={() => setShowOverlay((v) => !v)}
              className="btn-ghost px-2 py-1 text-xs"
              aria-pressed={showOverlay}
            >
              {showOverlay ? (
                <>
                  <EyeOff className="h-4 w-4" /> Hide regions
                </>
              ) : (
                <>
                  <Eye className="h-4 w-4" /> Show regions
                </>
              )}
            </button>
          )}
        </div>
      </div>

      <div className="relative bg-slate-100 dark:bg-slate-800">
        {showIframe ? (
          <iframe
            src={pdfSrc}
            title={`Document ${doc.filename}`}
            className="block h-[640px] w-full border-0"
          />
        ) : imageSrc ? (
          <img
            src={imageSrc}
            alt={`Document ${doc.filename}${
              showHeatmap && heatmapUrl ? " with forensic heatmap" : ""
            }`}
            className="block w-full"
          />
        ) : (
          <div className="flex h-80 flex-col items-center justify-center gap-2 text-slate-400">
            <ImageOff className="h-8 w-8" />
            <p className="text-sm">No preview available for this document.</p>
          </div>
        )}

        {showOverlay &&
          imageSrc &&
          markers.map((m) => {
            const active = activeRegionId === m.id;
            const color = m.pipeline === 1 ? (SEVERITY_COLOR[m.severity] ?? "#0d9488") : "#4f46e5";
            return (
              <button
                key={m.id}
                onClick={() => onRegionClick?.(m.id)}
                className={cx(
                  "absolute rounded-md border-2 transition-all",
                  active ? "z-10 shadow-lg" : "opacity-90 hover:opacity-100"
                )}
                style={{
                  left: `${m.region.x}%`,
                  top: `${m.region.y}%`,
                  width: `${m.region.w}%`,
                  height: `${m.region.h}%`,
                  borderColor: color,
                  backgroundColor: `${color}${active ? "33" : "1f"}`,
                  boxShadow: active ? `0 0 0 3px ${color}55` : undefined,
                }}
                aria-label={`Flagged region: ${m.label}`}
                title={m.label}
              >
                <span
                  className="absolute -top-5 left-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-bold text-white"
                  style={{ backgroundColor: color }}
                >
                  {m.label}
                </span>
              </button>
            );
          })}
      </div>

      {markers.length > 0 && (
        <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
          {markers.length} flagged region{markers.length > 1 ? "s" : ""} ·
          red = high, amber = medium, teal = low, indigo = content. Click a box to read its reason.
        </p>
      )}
    </div>
  );
}

function collectRegions(doc: DocumentResult): RegionMarker[] {
  const out: RegionMarker[] = [];
  doc.pipeline1.signals.forEach((s, i) => {
    if (s.region)
      out.push({ id: `p1-${i}`, region: s.region, label: s.label, pipeline: 1, severity: s.severity });
  });
  doc.pipeline2.signals.forEach((s, i) => {
    if (s.region)
      out.push({ id: `p2-${i}`, region: s.region, label: s.label, pipeline: 2, severity: s.severity });
  });
  return out;
}
