import type { DocumentResult, Signal } from "@/api/types";
import { SeverityBadge } from "./SeverityBadge";

/** Ordered signals across pipeline 1 and 2; rows with regions jump in the viewer. */
export function EvidenceTimeline({
  doc,
  onJump,
}: {
  doc: DocumentResult;
  onJump?: (strategy: { where: "Pipeline 1" | "Pipeline 2"; index: number; region?: unknown }) => void;
}) {
  const rows = [
    ...doc.pipeline1.signals.map((s, index) => ({ ...s, where: "Pipeline 1" as const, index })),
    ...doc.pipeline2.signals.map((s, index) => ({ ...s, where: "Pipeline 2" as const, index })),
  ].sort((a, b) => (b.severity === a.severity ? 0 : b.severity === "high" ? 1 : -1));

  return (
    <div className="card p-4">
      <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">Evidence timeline</h3>
      <ol className="space-y-2">
        {rows.map((r, i) => (
          <li key={i} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500">{r.where}</span>
              <SeverityBadge severity={r.severity} />
            </div>
            <p className="mt-1 text-sm font-semibold text-slate-200">{r.label}</p>
            <p className="text-xs text-slate-400">{r.reason}</p>
            {r.region && (
              <button
                className="mt-2 text-[11px] font-semibold text-teal-300 hover:underline"
                onClick={() => onJump?.({ where: r.where, index: r.index, region: r.region })}
              >
                Jump to region →
              </button>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

export type { Signal };
