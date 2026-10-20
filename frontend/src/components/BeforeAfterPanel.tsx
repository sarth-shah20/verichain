import { ArrowRight, FileWarning } from "lucide-react";
import type { RevisionEvidence } from "@/api/types";
import { cx } from "@/lib/format";

const KIND_LABELS: Record<string, string> = {
  identifier: "Identifier",
  amount: "Amount",
  date: "Date",
  name: "Name",
  text: "Text",
};

/**
 * Ocrolus-style before/after panel. When an edited PDF is detected, the prior
 * revision is still embedded in the file, so we can recover and show the
 * ORIGINAL value next to the current (edited) one — the single most convincing
 * piece of tamper evidence.
 */
export function BeforeAfterPanel({ evidence }: { evidence: RevisionEvidence }) {
  if (!evidence?.detected || evidence.changes.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-xl border border-red-200 bg-red-50/60 dark:border-red-900/50 dark:bg-red-950/30">
      <header className="flex items-center gap-2 border-b border-red-200 bg-red-100/70 px-4 py-3 dark:border-red-900/50 dark:bg-red-900/30">
        <FileWarning className="h-4 w-4 text-red-600 dark:text-red-400" />
        <h3 className="text-sm font-bold uppercase tracking-wide text-red-700 dark:text-red-300">
          Edited PDF — original values recovered
        </h3>
      </header>

      <div className="space-y-3 p-4">
        <p className="text-sm leading-relaxed text-red-800/90 dark:text-red-200/90">
          A prior revision of this PDF is still embedded in the file (an
          incremental-update edit). The original field value below was recovered
          from those bytes and compared with the current, edited value.
        </p>

        <ul className="space-y-2.5">
          {evidence.changes.map((c, i) => (
            <li
              key={i}
              className="rounded-lg border border-red-200 bg-white p-3 dark:border-red-900/50 dark:bg-slate-900"
            >
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="truncate text-xs font-semibold text-slate-600 dark:text-slate-300">
                  {c.field_hint ?? "Edited field"}
                </span>
                <span
                  className={cx(
                    "rounded-md px-2 py-0.5 text-[11px] font-semibold",
                    c.weight === "high"
                      ? "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"
                      : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                  )}
                >
                  {KIND_LABELS[c.kind] ?? c.kind}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <p className="text-[11px] uppercase tracking-wide text-slate-400">
                    Original
                  </p>
                  <p className="font-mono text-sm font-semibold text-slate-500 line-through decoration-slate-400">
                    {c.original_value}
                  </p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-red-500" />
                <div className="flex-1">
                  <p className="text-[11px] uppercase tracking-wide text-slate-400">
                    Edited to
                  </p>
                  <p className="font-mono text-sm font-bold text-red-600 dark:text-red-400">
                    {c.current_value}
                  </p>
                </div>
              </div>
              {c.page_number != null && (
                <p className="mt-1.5 text-[11px] text-slate-400">
                  Recovered from page {c.page_number}
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
