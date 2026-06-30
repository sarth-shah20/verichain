// ---------------------------------------------------------------------------
// VeriChain UI data model — the shape the client returns to the React app.
// This is the app's INTERNAL contract, intentionally richer than the backend's
// frozen HTTP contract (multi-document, async job model).
//
// The client (realClient.ts) adapts the backend's batch contract into this
// shape via adapter.ts — see adapter.ts for the wire-level backend types and
// the mapping.
// ---------------------------------------------------------------------------

export type Verdict = "genuine" | "review" | "high_risk";

export type DocType =
  | "bank_statement"
  | "land_record"
  | "itr"
  | "salary_slip"
  | "unknown";

export type Severity = "info" | "low" | "medium" | "high";

export type SignalFamily =
  | "provenance"
  | "structure"
  | "image"
  | "content"
  | "triangulation";

export type FieldStatus = "ok" | "mismatch" | "missing";

export type JobStatus = "processing" | "done" | "error";

/** A rectangular region on the document, expressed as percentages (0–100). */
export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Signal {
  family: SignalFamily;
  label: string;
  severity: Severity;
  reason: string;
  region?: Region | null;
}

export interface ExtractedField {
  key: string;
  value: string;
  status: FieldStatus;
}

export interface Pipeline1Report {
  /** Authenticity & forensics, normalised 0–100. */
  score: number;
  heatmap_url: string | null;
  signals: Signal[];
}

export interface Pipeline2Report {
  /** Content extraction & validation, normalised 0–100. */
  score: number;
  extracted_fields: ExtractedField[];
  signals: Signal[];
}

export interface DocumentResult {
  doc_id: string;
  filename: string;
  doc_type: DocType;
  thumbnail_url: string | null;
  /** Object URL of the actual uploaded file (image or PDF) for full preview. */
  preview_url?: string | null;
  /** Trust / authenticity score, 0–100. HIGHER = more genuine. */
  trust_score: number;
  verdict: Verdict;
  pipeline1: Pipeline1Report;
  pipeline2: Pipeline2Report;
}

export interface OverallResult {
  /** Trust / authenticity score, 0–100. HIGHER = more genuine. */
  trust_score: number;
  verdict: Verdict;
  confidence: number; // 0–1
  summary: string;
}

export interface CrossDocumentSignal {
  label: string;
  reason: string;
  severity: Severity;
}

export interface VerificationResult {
  application_id: string;
  submitted_at: string; // ISO 8601
  overall: OverallResult;
  documents: DocumentResult[];
  cross_document: CrossDocumentSignal[];
  flag_history_notes: string[];
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  progress: number; // 0–100
  result: VerificationResult | null;
}

export interface SubmitResponse {
  job_id: string;
}

/** A single document attached to a verification request. */
export interface SubmitFile {
  file: File;
  doc_type?: DocType;
}

export interface SubmitOptions {
  files: SubmitFile[];
  application_id?: string;
}

/** Compact history row (audit trail). */
export interface HistoryItem {
  job_id: string;
  application_id: string;
  submitted_at: string;
  document_count: number;
  verdict: Verdict;
  trust_score: number;
}

/** The interface the API client implements. */
export interface VeriChainApi {
  submit(options: SubmitOptions): Promise<SubmitResponse>;
  getStatus(jobId: string): Promise<JobStatusResponse>;
  getResult(jobId: string): Promise<VerificationResult>;
  getHistory(): Promise<HistoryItem[]>;
}
