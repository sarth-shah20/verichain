import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  CircleAlert,
  Info,
  CheckCircle2,
  XCircle,
  ClipboardCheck,
  Sparkles,
} from "lucide-react";
import { useResult } from "@/lib/useResult";
import { ScoreGauge } from "@/components/ScoreGauge";
import { VerdictPill } from "@/components/VerdictPill";
import { DocumentCard } from "@/components/DocumentCard";
import { SeverityBadge } from "@/components/SeverityBadge";
import { CardSkeleton, Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { useToast } from "@/app/toast";
import { formatDateTime } from "@/lib/format";

type Decision = "approved" | "review" | "rejected";

export function Results() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { result, loading, error, reload } = useResult(jobId);
  const [decision, setDecision] = useState<Decision | null>(null);

  if (loading) return <ResultsSkeleton />;

  if (error || !result) {
    return (
      <ErrorState
        title="Couldn't load results"
        description={error ?? "This verification could not be found."}
        onRetry={reload}
      />
    );
  }

  const { overall, documents, cross_document, flag_history_notes } = result;

  const act = (d: Decision, label: string) => {
    setDecision(d);
    toast(label, d === "rejected" ? "warning" : "success");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-400">Verification result</p>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {result.application_id}
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Submitted {formatDateTime(result.submitted_at)} · {documents.length}{" "}
            document{documents.length === 1 ? "" : "s"}
          </p>
        </div>
        {decision && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            <ClipboardCheck className="h-4 w-4" />
            {decision === "approved"
              ? "Approved"
              : decision === "review"
                ? "Sent to manual review"
                : "Rejected"}
          </span>
        )}
      </div>

      {/* Hero verdict */}
      <section className="card flex flex-col gap-6 p-6 md:flex-row md:items-center">
        <div className="flex shrink-0 justify-center">
          <ScoreGauge score={overall.trust_score} size={180} />
        </div>
        <div className="flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <VerdictPill verdict={overall.verdict} />
            <span className="text-sm text-slate-500 dark:text-slate-400">
              Confidence{" "}
              <span className="tnum font-semibold text-slate-700 dark:text-slate-200">
                {Math.round(overall.confidence * 100)}%
              </span>
            </span>
          </div>
          <p className="text-lg font-medium leading-relaxed text-slate-800 dark:text-slate-100">
            {overall.summary}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={() => act("approved", "Application approved.")}
              className="btn-primary"
            >
              <CheckCircle2 className="h-4 w-4" /> Approve
            </button>
            <button
              onClick={() => act("review", "Sent to manual review.")}
              className="btn-secondary"
            >
              <CircleAlert className="h-4 w-4" /> Send to manual review
            </button>
            <button
              onClick={() => act("rejected", "Application rejected.")}
              className="btn inline-flex border border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300"
            >
              <XCircle className="h-4 w-4" /> Reject
            </button>
          </div>
        </div>
      </section>

      {/* Cross-document signals */}
      {cross_document.length > 0 && (
        <section className="card border-l-4 border-l-risk-high p-5">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-risk-high">
            <Sparkles className="h-4 w-4" /> Cross-document findings
          </h2>
          <ul className="mt-3 space-y-3">
            {cross_document.map((c, i) => (
              <li
                key={i}
                className="flex items-start justify-between gap-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60"
              >
                <div>
                  <p className="font-semibold text-slate-800 dark:text-slate-100">
                    {c.label}
                  </p>
                  <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">
                    {c.reason}
                  </p>
                </div>
                <SeverityBadge severity={c.severity} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Document cards */}
      <section>
        <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-500">
          Documents
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {documents.map((doc) => (
            <DocumentCard
              key={doc.doc_id}
              doc={doc}
              onOpen={() => navigate(`/results/${jobId}/doc/${doc.doc_id}`)}
            />
          ))}
        </div>
      </section>

      {/* Flag history notes */}
      {flag_history_notes.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/50">
          <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-slate-400">
            <Info className="h-4 w-4" /> Flag-history notes
          </h2>
          <ul className="mt-2 space-y-1.5">
            {flag_history_notes.map((n, i) => (
              <li
                key={i}
                className="text-sm text-slate-600 dark:text-slate-300"
              >
                · {n}
              </li>
            ))}
          </ul>
        </section>
      )}

      <Link
        to="/history"
        className="inline-block text-sm font-semibold text-pipeline1 hover:underline dark:text-teal-300"
      >
        View all verifications →
      </Link>
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <div className="card flex gap-6 p-6">
        <Skeleton className="h-44 w-44 rounded-full" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-2/3" />
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>
    </div>
  );
}
