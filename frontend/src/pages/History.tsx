import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { History as HistoryIcon, FileSearch } from "lucide-react";
import { api } from "@/api";
import type { HistoryItem } from "@/api/types";
import { VerdictPill } from "@/components/VerdictPill";
import { EmptyState, ErrorState } from "@/components/States";
import { Skeleton } from "@/components/Skeleton";
import { colorForScore } from "@/lib/risk";
import { formatDateTime } from "@/lib/format";

export function History() {
  const navigate = useNavigate();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    api
      .getHistory()
      .then((data) => !cancelled && setItems(data))
      .catch(
        (e: unknown) =>
          !cancelled &&
          setError(e instanceof Error ? e.message : "Could not load history.")
      );
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          History
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Audit trail of past verifications. Click a row to reopen its results.
        </p>
      </header>

      {error ? (
        <ErrorState description={error} onRetry={() => setTick((t) => t + 1)} />
      ) : items === null ? (
        <div className="card divide-y divide-slate-100 dark:divide-slate-800">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 p-4">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-32" />
              <Skeleton className="ml-auto h-6 w-24" />
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="No verifications yet"
          description="Documents you verify will appear here as an audit trail."
          action={
            <button onClick={() => navigate("/new")} className="btn-primary">
              Start a verification
            </button>
          }
        />
      ) : (
        <div className="card overflow-hidden">
          {/* Desktop table */}
          <table className="hidden w-full text-sm sm:table">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800/50 dark:text-slate-400">
                <th className="px-5 py-3 font-semibold">Application</th>
                <th className="px-5 py-3 font-semibold">Submitted</th>
                <th className="px-5 py-3 font-semibold">Docs</th>
                <th className="px-5 py-3 font-semibold">Score</th>
                <th className="px-5 py-3 font-semibold">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.map((row) => (
                <tr
                  key={row.job_id}
                  onClick={() => navigate(`/results/${row.job_id}`)}
                  tabIndex={0}
                  onKeyDown={(e) =>
                    e.key === "Enter" && navigate(`/results/${row.job_id}`)
                  }
                  className="cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <td className="px-5 py-3.5 font-semibold text-slate-800 dark:text-slate-100">
                    {row.application_id}
                  </td>
                  <td className="px-5 py-3.5 text-slate-500 dark:text-slate-400">
                    {formatDateTime(row.submitted_at)}
                  </td>
                  <td className="px-5 py-3.5 text-slate-500 dark:text-slate-400">
                    {row.document_count}
                  </td>
                  <td className="px-5 py-3.5">
                    <span
                      className="tnum inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold text-white"
                      style={{ backgroundColor: colorForScore(row.risk_score) }}
                    >
                      {row.risk_score}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <VerdictPill verdict={row.verdict} size="sm" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Mobile list */}
          <ul className="divide-y divide-slate-100 dark:divide-slate-800 sm:hidden">
            {items.map((row) => (
              <li key={row.job_id}>
                <button
                  onClick={() => navigate(`/results/${row.job_id}`)}
                  className="flex w-full items-center gap-3 p-4 text-left"
                >
                  <FileSearch className="h-5 w-5 shrink-0 text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-slate-800 dark:text-slate-100">
                      {row.application_id}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {formatDateTime(row.submitted_at)} · {row.document_count}{" "}
                      docs
                    </p>
                  </div>
                  <VerdictPill verdict={row.verdict} size="sm" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
