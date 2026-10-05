import { useState } from "react";
import type { DocumentResult } from "@/api/types";

/** A/B slider: original page on the left, forensic heatmap on the right. */
export function HeatmapCompare({ doc }: { doc: DocumentResult }) {
  const [pct, setPct] = useState(50);
  const heatmap = doc.pipeline1.heatmap_url;
  const original = doc.preview_url ?? doc.thumbnail_url;
  if (!heatmap || !original) return null;
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-slate-800 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-200">A/B compare — original vs tamper heatmap</h3>
      </div>
      <div className="relative select-none bg-slate-950" onMouseMove={(e) => {
        if ((e.buttons & 1) !== 1) return;
        const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
        setPct(Math.min(100, Math.max(0, ((e.clientX - rect.left) / rect.width) * 100)));
      }}
      onMouseDown={(e) => {
        const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
        setPct(Math.min(100, Math.max(0, ((e.clientX - rect.left) / rect.width) * 100)));
      }}>
        <img src={heatmap} alt="heatmap" className="block w-full" />
        <img
          src={original}
          alt="original"
          className="absolute inset-0 block h-full w-full object-cover"
          style={{ clipPath: `inset(0 ${100 - pct}% 0 0)` }}
        />
        <div className="absolute inset-y-0 w-0.5 bg-white/80" style={{ left: `${pct}%` }} />
        {/* Left side shows ORIGINAL, right shows HEATMAP */}
        <div className="absolute left-2 top-2 rounded bg-slate-900/70 px-2 py-0.5 text-[10px] font-semibold text-slate-200">Original ←</div>
        <div className="absolute right-2 top-2 rounded bg-slate-900/70 px-2 py-0.5 text-[10px] font-semibold text-slate-200">→ Heatmap</div>
      </div>
    </div>
  );
}
