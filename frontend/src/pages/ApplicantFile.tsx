import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/app/toast";
import { useResult } from "@/lib/useResult";
import { DocumentViewer } from "@/components/DocumentViewer";
import { BeforeAfterPanel } from "@/components/BeforeAfterPanel";
import { EvidenceTimeline } from "@/components/EvidenceTimeline";
import { SignalCard } from "@/components/SignalCard";
import { FieldsTable } from "@/components/FieldsTable";
import { ScoreGauge } from "@/components/ScoreGauge";
import { VerdictPill } from "@/components/VerdictPill";
import { ErrorState, EmptyState } from "@/components/States";
import { Skeleton } from "@/components/Skeleton";
import { colorForScore } from "@/lib/risk";
import { docTypeLabel } from "@/lib/format";

export function ApplicantFile() {
  const { jobId } = useParams<{ jobId: string }>();
  const { result, loading, error, reload } = useResult(jobId);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [activeRegionId, setActiveRegionId] = useState<string | null>(null);
  const viewerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (result?.documents?.length && !activeDocId) setActiveDocId(result.documents[0].doc_id);
  }, [result, activeDocId]);

  const doc = useMemo(() => result?.documents.find((d) => d.doc_id === activeDocId) ?? result?.documents[0] ?? null, [result, activeDocId]);

  if (loading) return <AppSkeleton />;
  if (error || !result) return <ErrorState description={error ?? "Not found"} onRetry={reload} />;
  if (!doc) return <EmptyState title="No document" />;

  return (
    <div className="space-y-4">
      <Link to={`/results/${jobId}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-400 hover:text-teal-300">
        <ArrowLeft className="h-4 w-4" /> Back to results
      </Link>

      <header className="card flex items-center gap-5 p-5">
        <ScoreGauge score={result.overall.trust_score} size={84} strokeWidth={8} showVerdict={false} />
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-white">{result.application_id}</h1>
            <VerdictPill verdict={result.overall.verdict} />
          </div>
          <p className="mt-1 text-sm text-slate-400">{result.overall.summary}</p>
        </div>
        <div className="text-right text-xs text-slate-500">
          <p className="tnum text-lg font-bold text-slate-200">{result.documents.length}</p>
          docs
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[260px_1fr_360px]">
        {/* Left: document rail */}
        <aside className="card divide-y divide-slate-800 p-2">
          {result.documents.map((d) => (
            <button key={d.doc_id} onClick={() => setActiveDocId(d.doc_id)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${activeDocId === d.doc_id ? "bg-slate-800" : "hover:bg-slate-800/50"}`}>
              <span className="tnum inline-flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold text-white" style={{ backgroundColor: colorForScore(d.trust_score) }}>{d.trust_score}</span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-200">{d.filename}</p>
                <p className="text-[11px] text-slate-500">{docTypeLabel(d.doc_type)}</p>
              </div>
            </button>
          ))}
        </aside>

        {/* Center: viewer */}
        <section ref={viewerRef}>
          <DocumentViewer doc={doc} activeRegionId={activeRegionId} onRegionClick={setActiveRegionId} />
        </section>

        {/* Right: findings */}
        <aside className="space-y-4">
          {doc.revision_evidence?.detected && <BeforeAfterPanel evidence={doc.revision_evidence} />}
          <div className="card p-4">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">Signals</h3>
            <div className="space-y-2">
              {doc.pipeline1.signals.concat(doc.pipeline2.signals).slice(0, 6).map((s, i) => (
                <SignalCard key={i} signal={s} pipeline={i < doc.pipeline1.signals.length ? 1 : 2} />
              ))}
            </div>
          </div>
          <EvidenceTimeline
            doc={doc}
            onJump={({ where, index }) => {
              setActiveRegionId(`${where === "Pipeline 1" ? "p1" : "p2"}-${index}`);
              viewerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          />
          <div className="card p-4">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">Fields</h3>
            <FieldsTable fields={doc.pipeline2.extracted_fields} />
          </div>
        </aside>
      </div>

      {/* Cross-document trust checks */}
      {result.cross_document.length > 0 && (
        <section className="card p-4">
          <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">Cross-document trust checks</h3>
          <div className="space-y-2">
            {result.cross_document.map((c, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-slate-800/50 px-3 py-2">
                <span className="text-sm text-slate-200">{c.label}</span>
                <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase ${c.severity === 'high' ? 'bg-red-950 text-red-300' : c.severity === 'medium' ? 'bg-amber-950 text-amber-300' : 'bg-sky-950 text-sky-300'}`}>{c.severity}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Decision bar */}
      <DecisionBar jobId={jobId!} />
    </div>
  );
}

function DecisionBar({ jobId }: { jobId: string }) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();
  const act = async (d: string, label: string) => {
    if (!note.trim()) { toast("Add a reason note first.", "warning"); return; }
    setSaving(true);
    try {
      await api.recordDecision(jobId, d as any, note);
      toast(`${label} recorded.`, "success");
    } catch (e: any) {
      toast(e.message ?? "Failed", "warning");
    } finally { setSaving(false); }
  };
  return (
    <div className="card space-y-3 p-4">
      <h3 className="text-xs font-bold uppercase tracking-wide text-slate-400">Underwriter decision — note required</h3>
      <textarea className="input min-h-[70px]" placeholder="Reason for this decision…" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2">
        <button disabled={saving} onClick={() => act("approved", "Approved")} className="btn-primary">Approve</button>
        <button disabled={saving} onClick={() => act("review", "Manual review")} className="btn-secondary">Manual review</button>
        <button disabled={saving} onClick={() => act("rejected", "Rejected")} className="btn-secondary">Reject</button>
      </div>
    </div>
  );
}

function AppSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-24 w-full" />
      <div className="grid gap-4 lg:grid-cols-[260px_1fr_360px]">
        <Skeleton className="h-96 w-full" /><Skeleton className="h-96 w-full" /><Skeleton className="h-96 w-full" />
      </div>
    </div>
  );
}
