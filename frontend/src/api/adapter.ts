import type { DocType, DocumentResult, Finding, OverallResult, Severity, VerificationResult, Verdict, Reconciliation, DeterministicCheck } from "./types";

export type BackendDecision = "auto_approve" | "human_review" | "auto_reject";
export interface BackendFieldVerification { status: string; issuer: string; matched_fields: string[] }
export interface BackendVerifyResponse {
  risk_score: number; route_taken: string; decision: string; reasons: string[];
  blockchain_tx?: string; heatmap_url: string | null; field_verification: BackendFieldVerification;
  extracted_fields?: Record<string, unknown>;
  field_results?: { field: string; match: boolean | null }[];
  findings?: Finding[]; deterministic_checks?: DeterministicCheck[];
  content_status?: string; analysis_status?: string; analysis_warnings?: string[];
  page_assets?: { page_number: number; url: string }[];
  heatmap_pages?: { page_number: number; url: string }[];
  revision_evidence?: DocumentResult["revision_evidence"];
  suspect_regions?: { page: number; bbox_pct: { x: number; y: number; w: number; h: number }; confidence: string; signals: string[]; note: string }[];
}
export interface BackendBatchDocument extends BackendVerifyResponse { filename: string; document_type: string; doc_id?: string }
export interface BackendBatchOverall { risk_score: number; route_taken: string; decision: string; reasons: string[] }
export interface BackendCrossSignal { label: string; reason: string; severity: string }
export interface BackendBatchJob {
  job_id: string; status: string; progress: number; applicant_id: string; submitted_at: string;
  document_count: number; documents: BackendBatchDocument[]; cross_document: BackendCrossSignal[];
  overall: BackendBatchOverall | null; error: string | null; underwriter_decision?: string | null;
  reviewer_note?: string | null; analysis_status?: string; analysis_warnings?: string[];
  document_stages?: { filename: string; stage: string }[];
  reconciliation?: Reconciliation[]; demo_scenario?: VerificationResult["demo_scenario"];
}
export interface DocInput { resp: BackendVerifyResponse; filename: string; docType: DocType; thumbnailUrl: string | null; index: number; extractedFields?: Record<string, unknown> }
export const decisionToVerdict = (decision: string): Verdict => decision === "auto_approve" ? "genuine" : decision === "auto_reject" ? "high_risk" : "review";
export function toTrustScore(_decision: string, score: number): number { return Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : 70 }
const severity = (value: string): Severity => ["info", "low", "medium", "high"].includes(value) ? value as Severity : "medium";
const docType = (value: string): DocType => {
  const aliases: Record<string, DocType> = { payslip: "salary_slip", salaried_itr: "itr" };
  return aliases[value] ?? (["itr", "salary_slip", "land_record", "bank_statement"].includes(value) ? value as DocType : "unknown");
};
const url = (value: string | null | undefined, base: string): string | null => !value ? null : /^(https?:|blob:|data:)/.test(value) ? value : `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
const label = (key: string): string => key === "pan" ? "PAN" : key.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());

function mapDocument(input: DocInput, base: string): DocumentResult {
  const r = input.resp;
  const fields = input.extractedFields ?? r.extracted_fields ?? {};
  const findingList = (r.findings ?? []).map(f => ({ ...f, severity: severity(f.severity) }));
  const pages = (r.page_assets ?? []).map(p => ({ ...p, url: url(p.url, base)! }));
  const matches = new Set(r.field_verification.matched_fields);
  const fieldResults = new Map<string, boolean | null>();
  for (const fr of r.field_results ?? []) if (!fieldResults.has(fr.field) || fr.match === false) fieldResults.set(fr.field, fr.match);
  const extracted = Object.entries(fields).filter(([, v]) => !Array.isArray(v) && (v === null || typeof v !== "object")).map(([key, value]) => ({
    key: label(key), value: value == null || value === "" ? "—" : typeof value === "boolean" ? (value ? "Yes" : "No") : String(value),
    status: value == null || value === "" ? "missing" as const : fieldResults.get(key) === false ? "mismatch" as const : matches.has(key) || fieldResults.get(key) === true ? "ok" as const : "unverified" as const,
  }));
  const signals = findingList.filter(f => f.state !== "passed" && f.state !== "skipped").map(f => ({
    id: f.id, label: f.label, reason: f.detail, severity: f.severity, page: f.page,
    family: f.source === "forensics" ? "structure" as const : "content" as const, region: f.region ?? null,
  }));
  // Legacy reports retain readable reasons without inventing independent scores.
  if (!findingList.length) for (const [index, reason] of (r.reasons ?? []).entries()) signals.push({ id: `legacy_${index}`, label: reason.slice(0, 70), reason, severity: "medium", page: undefined, family: "content", region: null });
  return {
    doc_id: `doc_${input.index}`, filename: input.filename, doc_type: input.docType,
    thumbnail_url: pages[0]?.url ?? input.thumbnailUrl, preview_url: pages[0]?.url ?? input.thumbnailUrl,
    trust_score: toTrustScore(r.decision, r.risk_score), verdict: decisionToVerdict(r.decision),
    pipeline1: { status: r.analysis_status === "partial" ? "partial" : "checked", heatmap_url: url(r.heatmap_url, base),
      heatmap_pages: (r.heatmap_pages ?? []).map(p => ({ ...p, url: url(p.url, base) })),
      signals: signals.filter(s => s.family === "structure") },
    pipeline2: { status: r.content_status ?? r.field_verification.status, extracted_fields: extracted,
      signals: signals.filter(s => s.family !== "structure") },
    revision_evidence: r.revision_evidence ?? null, page_assets: pages, findings: findingList,
    raw_fields: fields, analysis_status: r.analysis_status ?? "legacy", analysis_warnings: r.analysis_warnings ?? [],
    deterministic_checks: r.deterministic_checks ?? [],
  };
}
function mapOverall(value: BackendBatchOverall | null): OverallResult {
  return { trust_score: toTrustScore(value?.decision ?? "human_review", value?.risk_score ?? 70),
    verdict: decisionToVerdict(value?.decision ?? "human_review"),
    summary: value?.reasons?.[0] ?? "This application needs a closer look before a decision can be made." };
}
export function buildResultFromBatch(job: BackendBatchJob, base: string, thumbnails: (string | null)[] = []): VerificationResult {
  return { application_id: job.applicant_id, submitted_at: job.submitted_at,
    overall: mapOverall(job.overall), documents: job.documents.map((d, i) => mapDocument({ resp: d, filename: d.filename, docType: docType(d.document_type), thumbnailUrl: thumbnails[i] ?? null, index: i }, base)),
    cross_document: (job.cross_document ?? []).map(c => ({ ...c, severity: severity(c.severity) })),
    flag_history_notes: [], underwriter_decision: ["approved", "review", "rejected"].includes(job.underwriter_decision ?? "") ? job.underwriter_decision as VerificationResult["underwriter_decision"] : null,
    reviewer_note: job.reviewer_note, analysis_status: job.analysis_status ?? "legacy", analysis_warnings: job.analysis_warnings ?? [], reconciliation: job.reconciliation ?? [], demo_scenario: job.demo_scenario };
}
export function buildVerificationResult(args: { applicationId: string; submittedAt: string; docs: DocInput[]; apiBase: string }): VerificationResult {
  const worst = [...args.docs].sort((a, b) => a.resp.risk_score - b.resp.risk_score)[0];
  return { application_id: args.applicationId, submitted_at: args.submittedAt,
    overall: mapOverall(worst ? { ...worst.resp } : null), documents: args.docs.map(d => mapDocument(d, args.apiBase)),
    cross_document: [], flag_history_notes: [], analysis_status: "legacy", analysis_warnings: [], reconciliation: [] };
}
