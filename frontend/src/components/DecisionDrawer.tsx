import { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import type { UnderwriterDecision, VerificationResult } from "@/api/types";
export function DecisionDrawer({ jobId, result, onSaved }: { jobId: string; result: VerificationResult; onSaved: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [note, setNote] = useState(result.reviewer_note ?? "");
  const [decision, setDecision] = useState<UnderwriterDecision>(result.underwriter_decision ?? (result.overall.verdict === "genuine" ? "approved" : result.overall.verdict === "high_risk" ? "rejected" : "review"));
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  useEffect(() => setNote(result.reviewer_note ?? ""), [result.reviewer_note]);
  return <><button className="btn-primary" onClick={() => dialog.current?.showModal()}>{result.underwriter_decision ? "Update decision" : "Record decision"}</button>
    <dialog ref={dialog} className="decision-dialog card p-6" aria-labelledby="decision-title"><form onSubmit={async e => { e.preventDefault(); setSaving(true); setError(""); try { await api.recordDecision(jobId, decision, note.trim()); dialog.current?.close(); onSaved(); } catch (e) { setError(e instanceof Error ? e.message : "Could not save."); } finally { setSaving(false); } }}>
      <p className="eyebrow">Human review</p><h2 id="decision-title" className="text-2xl font-bold mt-2">Your decision, with a reason.</h2><p className="page-description mt-2">The system provides evidence. You make the final call.</p>
      <label className="block mt-6 text-sm font-semibold">Decision<select className="input mt-2" value={decision} onChange={e => setDecision(e.target.value as UnderwriterDecision)}><option value="approved">Approve</option><option value="review">Request manual review</option><option value="rejected">Reject</option></select></label>
      <label className="block mt-4 text-sm font-semibold">Reviewer note <span className="text-rose-600">*</span><textarea required autoFocus className="input mt-2 min-h-32" value={note} onChange={e => setNote(e.target.value)} placeholder="Explain the evidence behind your decision…" /></label>
      {error && <p role="alert" className="text-sm text-rose-600 mt-3">{error}</p>}<div className="flex justify-end gap-2 mt-6"><button type="button" className="btn-secondary" disabled={saving} onClick={() => dialog.current?.close()}>Cancel</button><button disabled={saving || !note.trim()} className="btn-primary">{saving ? "Saving…" : "Save decision"}</button></div>
    </form></dialog></>;
}
