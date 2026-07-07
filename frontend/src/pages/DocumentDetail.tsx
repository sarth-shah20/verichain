import { useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Filter } from "lucide-react";
import { useResult } from "@/lib/useResult";
import type { Severity, Signal } from "@/api/types";
import { DocumentViewer } from "@/components/DocumentViewer";
import { BeforeAfterPanel } from "@/components/BeforeAfterPanel";
import { SignalCard } from "@/components/SignalCard";
import { PipelineBadge } from "@/components/PipelineBadge";
import { VerdictPill } from "@/components/VerdictPill";
import { FieldsTable } from "@/components/FieldsTable";
import { ScoreGauge } from "@/components/ScoreGauge";
import { ErrorState, EmptyState } from "@/components/States";
import { Skeleton } from "@/components/Skeleton";
import { DocTypeIcon } from "@/components/DocTypeIcon";
import { SEVERITY_ORDER, severityRank } from "@/lib/risk";
import { cx, docTypeLabel } from "@/lib/format";

const SEVERITY_FILTERS: Array<{ key: Severity | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
  { key: "info", label: "Info" },
];

interface IndexedSignal {
  signal: Signal;
  regionId: string;
}

export function DocumentDetail() {
  const { jobId, docId } = useParams<{ jobId: string; docId: string }>();
  const { result, loading, error, reload } = useResult(jobId);
  const [minSeverity, setMinSeverity] = useState<Severity | "all">("all");
  const [activeRegionId, setActiveRegionId] = useState<string | null>(null);
  const viewerRef = useRef<HTMLDivElement>(null);

  const doc = useMemo(
    () => result?.documents.find((d) => d.doc_id === docId) ?? null,
    [result, docId]
  );

  // Tag each signal with its region id (index-based to match DocumentViewer).
  const p1: IndexedSignal[] = useMemo(
    () =>
      (doc?.pipeline1.signals ?? []).map((signal, i) => ({
        signal,
        regionId: `p1-${i}`,
      })),
    [doc]
  );
  const p2: IndexedSignal[] = useMemo(
    () =>
      (doc?.pipeline2.signals ?? []).map((signal, i) => ({
        signal,
        regionId: `p2-${i}`,
      })),
    [doc]
  );

  if (loading) return <DetailSkeleton />;

  if (error || !result) {
    return (
      <ErrorState
        title="Couldn't load document"
        description={error ?? "This verification could not be found."}
        onRetry={reload}
      />
    );
  }

  if (!doc) {
    return (
      <EmptyState
        title="Document not found"
        description="This document is not part of the verification."
        action={
          <Link to={`/results/${jobId}`} className="btn-secondary">
            Back to results
          </Link>
        }
      />
    );
  }

  const passesFilter = (s: Signal) =>
    minSeverity === "all" ||
    severityRank(s.severity) >= severityRank(minSeverity);

  const p1Filtered = p1.filter((x) => passesFilter(x.signal));
  const p2Filtered = p2.filter((x) => passesFilter(x.signal));

  const jumpToRegion = (id: string) => {
    setActiveRegionId(id);
    viewerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const totalFiltered = p1Filtered.length + p2Filtered.length;

  return (
    <div className="space-y-5">
      <Link
        to={`/results/${jobId}`}
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-500 hover:text-pipeline1 dark:text-slate-400"
      >
        <ArrowLeft className="h-4 w-4" /> Back to dashboard
      </Link>

      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
            <DocTypeIcon type={doc.doc_type} className="h-6 w-6" />
          </span>
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">
              {doc.filename}
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {docTypeLabel(doc.doc_type)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <VerdictPill verdict={doc.verdict} />
          <ScoreGauge
            score={doc.trust_score}
            size={84}
            strokeWidth={8}
            showVerdict={false}
          />
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left: document + heatmap */}
        <div ref={viewerRef} className="space-y-4">
          <DocumentViewer
            doc={doc}
            activeRegionId={activeRegionId}
            onRegionClick={setActiveRegionId}
          />
          <div className="flex gap-3 text-xs">
            <PipelineBadge pipeline={1} />
            <PipelineBadge pipeline={2} />
          </div>
        </div>

        {/* Right: findings */}
        <div className="space-y-5">
          {/* Recovered before/after evidence for edited PDFs (headline signal) */}
          {doc.revision_evidence?.detected && (
            <BeforeAfterPanel evidence={doc.revision_evidence} />
          )}

          {/* Severity filter */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
              <Filter className="h-3.5 w-3.5" /> Severity
            </span>
            {SEVERITY_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setMinSeverity(f.key)}
                className={cx(
                  "rounded-full px-2.5 py-1 text-xs font-semibold transition-colors",
                  minSeverity === f.key
                    ? "bg-pipeline1 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          {totalFiltered === 0 ? (
            <EmptyState
              title="No signals at this severity"
              description="Try lowering the severity filter to see more findings."
            />
          ) : (
            <>
              {/* Pipeline 1 */}
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <PipelineBadge pipeline={1} />
                  <span className="text-xs font-semibold text-slate-400">
                    score {doc.pipeline1.score}
                  </span>
                </div>
                {p1Filtered.length === 0 ? (
                  <p className="text-sm text-slate-400">
                    No authenticity signals at this severity.
                  </p>
                ) : (
                  sortBySeverity(p1Filtered).map((x) => (
                    <SignalCard
                      key={x.regionId}
                      signal={x.signal}
                      pipeline={1}
                      active={activeRegionId === x.regionId}
                      onJumpToRegion={
                        x.signal.region
                          ? () => jumpToRegion(x.regionId)
                          : undefined
                      }
                    />
                  ))
                )}
              </section>

              {/* Pipeline 2 */}
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <PipelineBadge pipeline={2} />
                  <span className="text-xs font-semibold text-slate-400">
                    score {doc.pipeline2.score}
                  </span>
                </div>
                {p2Filtered.length === 0 ? (
                  <p className="text-sm text-slate-400">
                    No content signals at this severity.
                  </p>
                ) : (
                  sortBySeverity(p2Filtered).map((x) => (
                    <SignalCard
                      key={x.regionId}
                      signal={x.signal}
                      pipeline={2}
                      active={activeRegionId === x.regionId}
                      onJumpToRegion={
                        x.signal.region
                          ? () => jumpToRegion(x.regionId)
                          : undefined
                      }
                    />
                  ))
                )}
              </section>
            </>
          )}

          {/* Extracted fields */}
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-slate-500">
              Extracted fields
              <span className="font-normal normal-case text-slate-400">
                (Verification)
              </span>
            </h2>
            <FieldsTable fields={doc.pipeline2.extracted_fields} />
          </section>
        </div>
      </div>
    </div>
  );
}

function sortBySeverity(list: IndexedSignal[]): IndexedSignal[] {
  return [...list].sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.signal.severity) -
      SEVERITY_ORDER.indexOf(b.signal.severity)
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-10 w-64" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-[520px] w-full rounded-xl" />
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-40 w-full rounded-lg" />
        </div>
      </div>
    </div>
  );
}
