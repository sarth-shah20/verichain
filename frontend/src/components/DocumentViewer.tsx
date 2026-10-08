import { useState } from "react";
import type { DocumentResult } from "@/api/types";
export function DocumentViewer({ doc, activeRegionId, onRegionClick, page = 1, onPageChange }: { doc: DocumentResult; activeRegionId?: string | null; onRegionClick?: (id: string) => void; page?: number; onPageChange?: (page: number) => void; heatmapUrlOverride?: string | null }) {
  const [heatmap, setHeatmap] = useState(false); const [zoom, setZoom] = useState(100); const [regions, setRegions] = useState(true);
  const original = doc.page_assets.find(p => p.page_number === page)?.url;
  const heat = doc.pipeline1.heatmap_pages?.find(p => p.page_number === page)?.url;
  const source = heatmap && heat ? heat : original ?? (page === 1 ? doc.preview_url : null);
  const findings = doc.findings.filter(f => f.page === page && f.region);
  return <div className="card overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-2 p-3 border-b" style={{ borderColor: "var(--line)" }}>
    <label className="text-xs font-semibold">Page <select aria-label="Document page" className="input inline-block w-auto py-1 ml-1" value={page} onChange={e => onPageChange?.(Number(e.target.value))}>{(doc.page_assets.length ? doc.page_assets : [{ page_number: 1 }]).map(p => <option key={p.page_number} value={p.page_number}>{p.page_number}</option>)}</select></label>
    <div className="flex gap-2"><button className="btn-ghost text-xs" disabled={!heat} aria-pressed={heatmap} onClick={() => setHeatmap(!heatmap)}>{heatmap ? "Original" : "Heatmap"}</button><button className="btn-ghost text-xs" aria-pressed={regions} onClick={() => setRegions(!regions)}>Regions</button><select className="input w-auto py-1 text-xs" aria-label="Zoom" value={zoom} onChange={e => setZoom(Number(e.target.value))}>{[75,100,125,150].map(z => <option key={z} value={z}>{z}%</option>)}</select></div></div>
    <div className="viewer-canvas overflow-auto p-4"><div className="document-paper relative mx-auto" style={{ width: `${zoom}%`, minWidth: zoom > 100 ? `${zoom}%` : undefined }}>
      {source ? /\.pdf(?:$|\?)/i.test(source) ? <iframe title={doc.filename} src={source} className="w-full h-[650px]" /> : <img src={source} alt={`${doc.filename}, page ${page}`} className="block w-full" /> : <p className="p-10 text-center text-sm">Original preview unavailable for this older report.</p>}
      {original && regions && findings.map(f => <button key={f.id} aria-label={f.label} title={f.detail} onClick={() => onRegionClick?.(f.id)} className="absolute border-2 rounded" style={{ left: `${f.region!.x}%`, top: `${f.region!.y}%`, width: `${f.region!.w}%`, height: `${f.region!.h}%`, borderColor: f.severity === "high" ? "#e05252" : "#d99a21", background: activeRegionId === f.id ? "#e0525233" : "transparent" }} />)}
    </div></div><p className="text-xs px-4 py-3" style={{ color: "var(--muted)" }}>Page {page} · {heatmap && heat ? "Forensic overlay" : "Original document"} · {findings.length} localized findings</p></div>;
}
