import { useState } from "react";
import { Eye, EyeOff, ImageOff } from "lucide-react";
import type { DocumentResult, Region } from "@/api/types";
import { cx } from "@/lib/format";

interface RegionMarker {
  id: string;
  region: Region;
  label: string;
  pipeline: 1 | 2;
}

interface DocumentViewerProps {
  doc: DocumentResult;
  /** Currently highlighted region id (e.g. clicked from a signal). */
  activeRegionId?: string | null;
  onRegionClick?: (id: string) => void;
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
}: DocumentViewerProps) {
  const [showOverlay, setShowOverlay] = useState(true);

  // A PDF upload renders in an embedded viewer; images (and forensic heatmaps)
  // render as a bitmap with clickable region overlays.
  const isPdf = /\.pdf$/i.test(doc.filename);
  const pdfSrc = isPdf ? (doc.preview_url ?? null) : null;
  // Prefer the forensic heatmap when present, otherwise the real preview, then
  // the card thumbnail as a last resort.
  const imageSrc =
    doc.pipeline1.heatmap_url ?? (isPdf ? null : (doc.preview_url ?? doc.thumbnail_url));
  const markers = collectRegions(doc);

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Document {doc.pipeline1.heatmap_url ? "· heatmap" : "preview"}
        </h3>
        {markers.length > 0 && (
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

      <div className="relative bg-slate-100 dark:bg-slate-800">
        {pdfSrc ? (
          <iframe
            src={pdfSrc}
            title={`Document ${doc.filename}`}
            className="block h-[640px] w-full border-0"
          />
        ) : imageSrc ? (
          <img
            src={imageSrc}
            alt={`Document ${doc.filename}${
              doc.pipeline1.heatmap_url ? " with forensic heatmap" : ""
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
            const color = m.pipeline === 1 ? "#0d9488" : "#4f46e5";
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
          teal = authenticity, indigo = content. Click a box to read its reason.
        </p>
      )}
    </div>
  );
}

function collectRegions(doc: DocumentResult): RegionMarker[] {
  const out: RegionMarker[] = [];
  doc.pipeline1.signals.forEach((s, i) => {
    if (s.region)
      out.push({ id: `p1-${i}`, region: s.region, label: s.label, pipeline: 1 });
  });
  doc.pipeline2.signals.forEach((s, i) => {
    if (s.region)
      out.push({ id: `p2-${i}`, region: s.region, label: s.label, pipeline: 2 });
  });
  return out;
}
