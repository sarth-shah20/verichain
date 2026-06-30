import type { Signal } from "@/api/types";
import { SeverityBadge } from "./SeverityBadge";
import { cx } from "@/lib/format";

const FAMILY_LABELS: Record<Signal["family"], string> = {
  provenance: "Provenance",
  structure: "Structure",
  image: "Image forensics",
  content: "Content",
  triangulation: "Triangulation",
};

interface SignalCardProps {
  signal: Signal;
  pipeline: 1 | 2;
  /** Whether this signal has a clickable region on the document. */
  onJumpToRegion?: () => void;
  active?: boolean;
}

export function SignalCard({
  signal,
  pipeline,
  onJumpToRegion,
  active,
}: SignalCardProps) {
  const accent =
    pipeline === 1
      ? "border-l-pipeline1"
      : "border-l-pipeline2";
  const hasRegion = !!signal.region;

  return (
    <div
      className={cx(
        "rounded-lg border border-l-4 border-slate-200 bg-white p-4 transition-colors dark:border-slate-800 dark:bg-slate-900",
        accent,
        active && "ring-2 ring-pipeline1"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
            {FAMILY_LABELS[signal.family]}
          </p>
          <h4 className="mt-0.5 font-semibold text-slate-800 dark:text-slate-100">
            {signal.label}
          </h4>
        </div>
        <SeverityBadge severity={signal.severity} />
      </div>
      <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {signal.reason}
      </p>
      {hasRegion && onJumpToRegion && (
        <button
          onClick={onJumpToRegion}
          className="mt-3 text-xs font-semibold text-pipeline1 hover:underline dark:text-teal-300"
        >
          Show on document →
        </button>
      )}
    </div>
  );
}
