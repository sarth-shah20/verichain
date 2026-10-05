import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import type { HistoryItem, Verdict } from "@/api/types";
import { VerdictPill } from "@/components/VerdictPill";
import { EmptyState, ErrorState } from "@/components/States";
import { Skeleton } from "@/components/Skeleton";
import { colorForScore } from "@/lib/risk";
import { cx, formatDateTime } from "@/lib/format";
import { ListFilter, ArrowUpDown, ShieldAlert, Clock, CheckCircle2 } from "lucide-react";

const FILTERS: Array<{ key: "all" | Verdict | "pending"; label: string }> = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending decision" },
  { key: "high_risk", label: "High risk" },
  { key: "review", label: "Needs review" },
  { key: "genuine", label: "Clean" },
];

export function Queue() {
  const navigate = useNavigate();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [sortAsc, setSortAsc] = useState(true); // worst trust first
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [refreshedAt, setRefreshedAt] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setItems(null); setError(null);
    api.getHistory()
      .then((d) => { if (!cancelled) { setItems(d); setRefreshedAt(new Date().toLocaleTimeString()); } })
      .catch((e) => !cancelled && setError(String(e)));
    return () => { cancelled = true; };
  }, [tick]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 20000);
    return () => clearInterval(id);
  }, []);

  const rows = useMemo(() => {
    let r = items ?? [];
    if (filter === "pending") r = r.filter((x) => !x.underwriter_decision);
    else if (filter !== "all") r = r.filter((x) => x.verdict === filter);
    r = [...r].sort((a, b) => sortAsc ? a.trust_score - b.trust_score : b.trust_score - a.trust_score);
    return r;
  }, [items, filter, sortAsc]);

  const stats = useMemo(() => {
    const it = items ?? [];
    return {
      total: it.length,
      pending: it.filter((x) => !x.underwriter_decision).length,
      high: it.filter((x) => x.verdict === "high_risk").length,
      clean: it.filter((x) => x.verdict === "genuine").length,
    };
  }, [items]);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Verification queue</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Review the worst-risk files first.</p>
        </div>
        <div className="flex items-center gap-3">
          {refreshedAt && <span className="text-[11px] text-slate-500">Updated {refreshedAt} · auto-refresh 20s</span>}
          <button onClick={() => setTick((t) => t + 1)} className="btn-secondary">Refresh</button>
        </div>
        <button
          className="btn-secondary"
          onClick={() => {
            const header = "application_id,docs,submitted_at,trust_score,verdict,decision\n";
            const body = rows
              .map((r) => `${r.application_id},${(r.doc_names ?? "").replace(/,/g, ";")},${r.submitted_at},${r.trust_score},${r.verdict},${r.underwriter_decision ?? ""}`)
              .join("\n");
            const url = URL.createObjectURL(new Blob([header + body], { type: "text/csv" }));
            const a = document.createElement("a");
            a.href = url; a.download = "verichain-queue.csv"; a.click();
            URL.revokeObjectURL(url);
          }}
        >
          Export CSV
        </button>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Total" value={stats.total} icon={<Clock className="h-4 w-4" />} />
        <Stat label="Pending" value={stats.pending} icon={<ListFilter className="h-4 w-4" />} />
        <Stat label="High risk" value={stats.high} icon={<ShieldAlert className="h-4 w-4" />} />
        <Stat label="Clean" value={stats.clean} icon={<CheckCircle2 className="h-4 w-4" />} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={cx("rounded-full px-3 py-1 text-xs font-semibold",
              filter === f.key ? "bg-pipeline1 text-white" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300")}>
            {f.label}
          </button>
        ))}
        <button onClick={() => setSortAsc((s) => !s)} className="btn-ghost px-2 py-1 text-xs" title="Toggle sort">
          <ArrowUpDown className="h-3.5 w-3.5" /> {sortAsc ? "Worst first" : "Best first"}
        </button>
      </div>

      {selectedIds.size > 0 && (
        <div className="card flex flex-wrap items-center gap-3 p-3">
          <span className="text-xs font-semibold text-slate-300">{selectedIds.size} selected</span>
          <button
            className="btn-secondary"
            onClick={async () => {
              await Promise.allSettled([...selectedIds].map((id) => api.recordDecision(id, "review")));
              setSelectedIds(new Set()); setTick((t) => t + 1);
            }}
          >
            Mark review
          </button>
          <button
            className="btn-secondary"
            onClick={async () => {
              await Promise.allSettled([...selectedIds].map((id) => api.recordDecision(id, "rejected")));
              setSelectedIds(new Set()); setTick((t) => t + 1);
            }}
          >
            Mark rejected
          </button>
          <button className="btn-ghost" onClick={() => setSelectedIds(new Set())}>Clear</button>
        </div>
      )}

      {error ? (
        <ErrorState description={error} onRetry={() => setTick((t) => t + 1)} />
      ) : items === null ? (
        <div className="card space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
      ) : rows.length === 0 ? (
        <EmptyState title="Queue empty" description="No verifications match this filter." />
      ) : (
        <div className="card overflow-hidden divide-y divide-slate-800">
          {rows.map((r) => (
            <div key={r.job_id} className="flex items-center gap-2 px-3 py-2 hover:bg-slate-800/40">
              <input
                type="checkbox"
                checked={selectedIds.has(r.job_id)}
                onChange={(e) => setSelectedIds((prev) => { const n = new Set(prev); e.target.checked ? n.add(r.job_id) : n.delete(r.job_id); return n; })}
                aria-label={`Select ${r.application_id}`}
              />
              <button onClick={() => navigate(`/results/${r.job_id}`)}
                className="flex w-full items-center gap-4 text-left">
                <span className="tnum inline-flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold text-white" style={{ backgroundColor: colorForScore(r.trust_score) }}>{r.trust_score}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-slate-100">{r.application_id}</p>
                  <p className="truncate text-xs text-slate-400">{r.doc_names ?? "—"} · {formatDateTime(r.submitted_at)}</p>
                </div>
                <VerdictPill verdict={r.verdict} size="sm" />
                {!r.underwriter_decision && <span className="rounded bg-amber-950 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-300">pending</span>}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="card flex items-center gap-3 p-3">
      <span className="text-teal-400">{icon}</span>
      <div>
        <p className="tnum text-lg font-bold leading-none text-slate-100">{value}</p>
        <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      </div>
    </div>
  );
}
