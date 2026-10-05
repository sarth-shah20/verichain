import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { History as HistoryIcon, FileSearch, Trash2, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import type { HistoryItem } from "@/api/types";
import { VerdictPill } from "@/components/VerdictPill";
import { EmptyState, ErrorState } from "@/components/States";
import { Skeleton } from "@/components/Skeleton";
import { colorForScore } from "@/lib/risk";
import { cx, formatDateTime } from "@/lib/format";
import { useToast } from "@/app/toast";

const DECISION_LABEL: Record<string, string> = {
  approved: "Approved",
  review: "Manual review",
  rejected: "Rejected",
};

export function History() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<HistoryItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");
  const [verdictFilter, setVerdictFilter] = useState<string>("all");

  const filtered = (items ?? []).filter((it) => {
    const q = query.trim().toLowerCase();
    const okQ =
      !q ||
      it.application_id.toLowerCase().includes(q) ||
      (it.doc_names ?? "").toLowerCase().includes(q);
    const okV = verdictFilter === "all" || it.verdict === verdictFilter;
    return okQ && okV;
  });

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

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.deleteVerification(pendingDelete.job_id);
      setItems((prev) => prev?.filter((r) => r.job_id !== pendingDelete.job_id) ?? null);
      toast("Verification removed from history.", "success");
      setPendingDelete(null);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete.", "warning");
    } finally {
      setDeleting(false);
    }
  };

  const open = (jobId: string) => navigate(`/results/${jobId}`);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">History</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Every verification is saved here. Click a row to reopen its full report.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <input
          className="input w-full max-w-sm"
          placeholder="Search application id or filename…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="input w-40"
          value={verdictFilter}
          onChange={(e) => setVerdictFilter(e.target.value)}
        >
          <option value="all">All verdicts</option>
          <option value="genuine">Genuine</option>
          <option value="review">Review</option>
          <option value="high_risk">High risk</option>
        </select>
        <span className="text-xs text-slate-400">{filtered.length} result(s)</span>
      </div>

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
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="No verifications yet"
          description="Documents you verify will appear here, and stay here."
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
                <th className="px-5 py-3 font-semibold">Application &amp; documents</th>
                <th className="px-5 py-3 font-semibold">Submitted</th>
                <th className="px-5 py-3 font-semibold">Score</th>
                <th className="px-5 py-3 font-semibold">Verdict</th>
                <th className="px-5 py-3 font-semibold">Decision</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {filtered.map((row) => (
                <tr
                  key={row.job_id}
                  onClick={() => open(row.job_id)}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && open(row.job_id)}
                  className="cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <td className="px-5 py-3.5">
                    <p className="font-semibold text-slate-800 dark:text-slate-100">
                      {row.application_id}
                    </p>
                    <p className="mt-0.5 max-w-[280px] truncate text-xs text-slate-500 dark:text-slate-400">
                      {row.doc_names || `${row.document_count} document(s)`}
                    </p>
                  </td>
                  <td className="px-5 py-3.5 text-slate-500 dark:text-slate-400">
                    {formatDateTime(row.submitted_at)}
                  </td>
                  <td className="px-5 py-3.5">
                    <span
                      className="tnum inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold text-white"
                      style={{ backgroundColor: colorForScore(row.trust_score) }}
                    >
                      {row.trust_score}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <VerdictPill verdict={row.verdict} size="sm" />
                  </td>
                  <td className="px-5 py-3.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                    {row.underwriter_decision ? DECISION_LABEL[row.underwriter_decision] : "—"}
                  </td>
                  <td className="px-3 py-3.5 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setPendingDelete(row);
                      }}
                      className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40"
                      aria-label={`Delete verification for ${row.application_id}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Mobile list */}
          <ul className="divide-y divide-slate-100 dark:divide-slate-800 sm:hidden">
            {filtered.map((row) => (
              <li key={row.job_id} className="flex items-center gap-2 p-4">
                <button
                  onClick={() => open(row.job_id)}
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                >
                  <FileSearch className="h-5 w-5 shrink-0 text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-slate-800 dark:text-slate-100">
                      {row.application_id}
                    </p>
                    <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                      {row.doc_names || `${row.document_count} docs`} ·{" "}
                      {formatDateTime(row.submitted_at)}
                    </p>
                  </div>
                  <VerdictPill verdict={row.verdict} size="sm" />
                </button>
                <button
                  onClick={() => setPendingDelete(row)}
                  className="rounded-md p-2 text-slate-400 hover:text-red-600"
                  aria-label={`Delete verification for ${row.application_id}`}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Delete confirmation dialog */}
      {pendingDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => !deleting && setPendingDelete(null)}
        >
          <div
            className="card w-full max-w-sm p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-50 text-red-600 dark:bg-red-950/40">
                <AlertTriangle className="h-5 w-5" />
              </span>
              <div>
                <h2 className="font-bold text-slate-900 dark:text-white">
                  Delete this verification?
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {pendingDelete.application_id} will be removed from History. The
                  audit-log record is preserved.
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setPendingDelete(null)}
                disabled={deleting}
                className="btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className={cx(
                  "btn inline-flex border border-transparent bg-red-600 font-semibold text-white hover:bg-red-700"
                )}
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
