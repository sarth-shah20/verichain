import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { api } from "@/api";
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
import { IncomeReconcileCard } from "@/components/IncomeReconcileCard";
import { CardSkeleton, Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { useToast } from "@/app/toast";
import { cx, formatDateTime } from "@/lib/format";

type Decision = "approved" | "review" | "rejected";

export function Results() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { result, loading, error, reload } = useResult(jobId);
  const [decision, setDecision] = useState<Decision | null>(null);

  // Restore a previously-recorded decision so it survives reload / reopen.
  useEffect(() => {
    if (result?.underwriter_decision) setDecision(result.underwriter_decision);
  }, [result?.underwriter_decision]);

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

  const act = async (d: Decision, label: string) => {
    if (!jobId) return;
    const prev = decision;
    setDecision(d); // optimistic
    try {
      await api.recordDecision(jobId, d);
      toast(label, d === "rejected" ? "warning" : "success");
    } catch (e) {
      setDecision(prev); // roll back on failure
      toast(e instanceof Error ? e.message : "Could not record decision.", "warning");
    }
  };

  // The system already has a recommendation (the verdict). Surface it on the
  // matching action so the underwriter sees "system recommends, human decides".
  const RECOMMENDED: Record<typeof overall.verdict, Decision> = {
    genuine: "approved",
    review: "review",
    high_risk: "rejected",
  };
  const recommended = RECOMMENDED[overall.verdict];

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
        <div className="flex shrink-0 flex-col items-center gap-2">
          <ScoreGauge score={overall.trust_score} size={180} />
          <p className="max-w-[190px] text-center text-xs text-slate-400">
            Trust score — higher is more trustworthy
          </p>
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
          <p className="pb-1">
            <Link to={`/app/${jobId}`} className="text-sm font-semibold text-pipeline1 hover:underline">
              Open applicant file workspace →
            </Link>
          </p>
          <div className="pt-1">
            <p className="mb-1.5 text-xs font-medium text-slate-400">
              System recommends — you decide:
            </p>
            <div className="flex flex-wrap items-stretch gap-2">
              <ActionButton
                label="Approve"
                icon={CheckCircle2}
                onClick={() => act("approved", "Application approved.")}
                recommended={recommended === "approved"}
                tone="green"
              />
              <ActionButton
                label="Send to manual review"
                icon={CircleAlert}
                onClick={() => act("review", "Sent to manual review.")}
                recommended={recommended === "review"}
                tone="amber"
              />
              <ActionButton
                label="Reject"
                icon={XCircle}
                onClick={() => act("rejected", "Application rejected.")}
                recommended={recommended === "rejected"}
                tone="red"
              />
            </div>
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

      {/* Income reconciliation (visual) */}
      <IncomeReconcileCard documents={documents} />

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

const TONE_STYLES: Record<
  "green" | "amber" | "red",
  { rec: string; plain: string; ring: string }
> = {
  green: {
    rec: "bg-green-600 text-white hover:bg-green-700 border-transparent",
    plain:
      "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
    ring: "ring-green-500/40",
  },
  amber: {
    rec: "bg-amber-500 text-white hover:bg-amber-600 border-transparent",
    plain:
      "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
    ring: "ring-amber-500/40",
  },
  red: {
    rec: "bg-red-600 text-white hover:bg-red-700 border-transparent",
    plain:
      "border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300",
    ring: "ring-red-500/40",
  },
};

function ActionButton({
  label,
  icon: Icon,
  onClick,
  recommended,
  tone,
}: {
  label: string;
  icon: typeof CheckCircle2;
  onClick: () => void;
  recommended: boolean;
  tone: "green" | "amber" | "red";
}) {
  const t = TONE_STYLES[tone];
  return (
    <div className="relative">
      {recommended && (
        <span className="absolute -top-2 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white shadow dark:bg-white dark:text-slate-900">
          Recommended
        </span>
      )}
      <button
        onClick={onClick}
        className={cx(
          "btn inline-flex border font-semibold",
          recommended ? t.rec : t.plain,
          recommended && `ring-2 ring-offset-2 ring-offset-white dark:ring-offset-slate-900 ${t.ring}`
        )}
      >
        <Icon className="h-4 w-4" /> {label}
      </button>
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
