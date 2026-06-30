import { Flag, ChevronRight } from "lucide-react";
import type { DocumentResult } from "@/api/types";
import { VerdictPill } from "./VerdictPill";
import { DocTypeIcon } from "./DocTypeIcon";
import { docTypeLabel } from "@/lib/format";
import { colorForScore } from "@/lib/risk";

interface DocumentCardProps {
  doc: DocumentResult;
  onOpen: () => void;
}

export function DocumentCard({ doc, onOpen }: DocumentCardProps) {
  const signalCount =
    doc.pipeline1.signals.length + doc.pipeline2.signals.length;
  const flaggedCount =
    doc.pipeline1.signals.filter((s) => s.severity !== "info").length +
    doc.pipeline2.signals.filter((s) => s.severity !== "info").length;

  return (
    <button
      onClick={onOpen}
      className="card group flex w-full flex-col overflow-hidden text-left transition-shadow hover:shadow-lg focus-visible:shadow-lg"
    >
      <div className="relative h-40 overflow-hidden bg-slate-100 dark:bg-slate-800">
        {doc.thumbnail_url ? (
          <img
            src={doc.thumbnail_url}
            alt={`Preview of ${doc.filename}`}
            className="h-full w-full object-cover object-top"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-slate-400">
            <DocTypeIcon type={doc.doc_type} className="h-10 w-10" />
          </div>
        )}
        <span
          className="absolute right-3 top-3 inline-flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold text-white shadow"
          style={{ backgroundColor: colorForScore(doc.trust_score) }}
          aria-label={`Trust score ${doc.trust_score}`}
        >
          {doc.trust_score}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start gap-2">
          <DocTypeIcon
            type={doc.doc_type}
            className="mt-0.5 h-5 w-5 shrink-0 text-slate-400"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-slate-800 dark:text-slate-100">
              {doc.filename}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {docTypeLabel(doc.doc_type)}
            </p>
          </div>
        </div>
        <div className="mt-auto flex items-center justify-between">
          <VerdictPill verdict={doc.verdict} size="sm" />
          <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
            <Flag className="h-3.5 w-3.5" />
            {flaggedCount} flagged · {signalCount} signals
          </span>
        </div>
      </div>
      <div className="flex items-center justify-end gap-1 border-t border-slate-100 px-4 py-2 text-xs font-semibold text-pipeline1 dark:border-slate-800 dark:text-teal-300">
        View evidence
        <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
      </div>
    </button>
  );
}
