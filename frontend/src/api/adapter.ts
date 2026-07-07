// ---------------------------------------------------------------------------
// Backend-contract adapter.
//
// The UI works with a rich, multi-document model (see types.ts). The REAL
// backend exposes the *frozen* VeriChain HTTP contract, which is flatter,
// single-document and synchronous. This module declares the real wire types
// and the pure mapping functions that translate a backend /verify response
// into the UI's DocumentResult / VerificationResult shapes.
//
// IMPORTANT — score direction:
//   The backend `risk_score` is actually an AUTHENTICITY score (higher = more
//   genuine: 96 ≈ approve, 18 ≈ reject). The UI now shows a TRUST score with the
//   SAME direction (higher = more genuine), so we pass it through (no inversion)
//   and clamp it into the band that matches the authoritative `decision`, so the
//   gauge colour can never disagree with the verdict pill.
// ---------------------------------------------------------------------------

import type {
  DocType,
  DocumentResult,
  ExtractedField,
  OverallResult,
  RevisionEvidence,
  Severity,
  Signal,
  SignalFamily,
  Verdict,
  VerificationResult,
} from "./types";
import { TRUST_THRESHOLDS } from "@/lib/risk";
import { docPlaceholder } from "@/lib/placeholders";

// ── Frozen backend wire types (mirror README.md /verify contract) ────────────

export type BackendDecision = "auto_approve" | "human_review" | "auto_reject";

export interface BackendFieldVerification {
  status: "verified" | "mismatch" | "unverifiable" | string;
  issuer: string;
  matched_fields: string[];
}

export interface BackendRevisionChange {
  field_hint: string | null;
  original_value: string;
  current_value: string;
  kind: string;
  weight: string;
  page_number: number;
  bbox: [number, number, number, number] | null;
}

export interface BackendRevisionEvidence {
  detected: boolean;
  summary: string | null;
  changes: BackendRevisionChange[];
}

export interface BackendVerifyResponse {
  /** AUTHENTICITY score, 0–100 (higher = more genuine). */
  risk_score: number;
  route_taken: string; // route_1 | route_2 | route_3
  decision: BackendDecision | string;
  reasons: string[];
  blockchain_tx: string;
  heatmap_url: string | null;
  field_verification: BackendFieldVerification;
  /** Additive (batch only): recovered before/after PDF-revision evidence. */
  revision_evidence?: BackendRevisionEvidence | null;
}

export interface BackendHistoryEvent {
  timestamp: string;
  doc_hash: string;
  risk_score: number;
  decision: string;
  tx_hash: string;
}

export interface BackendHistoryResponse {
  applicant_id: string;
  events: BackendHistoryEvent[];
}

// ── Verdict / score mapping ──────────────────────────────────────────────────

const DECISION_TO_VERDICT: Record<string, Verdict> = {
  auto_approve: "genuine",
  human_review: "review",
  auto_reject: "high_risk",
};

const DECISION_RANK: Record<string, number> = {
  auto_approve: 1,
  human_review: 2,
  auto_reject: 3,
};

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

export function decisionToVerdict(decision: string): Verdict {
  return DECISION_TO_VERDICT[decision] ?? "review";
}

/**
 * Map the backend authenticity score (higher = genuine) to the UI's TRUST score
 * (also higher = genuine), clamped into the band that matches the authoritative
 * `decision`. This guarantees the gauge (which derives colour from the score via
 * TRUST_THRESHOLDS) always agrees with the verdict pill.
 */
// Displayed trust is kept off the absolute extremes: no document reads as 0
// (never "certainly fraudulent") or 100 ("certainly genuine"), leaving visible
// headroom for model error. These bounds sit INSIDE every verdict band
// (DISPLAY_FLOOR is still high-risk, DISPLAY_CEIL still genuine), so the gauge
// colour and the verdict pill can never disagree.
const DISPLAY_FLOOR = 15;
const DISPLAY_CEIL = 95;

export function toTrustScore(decision: string, authScore: number): number {
  const trust = clamp(Math.round(authScore), 0, 100);
  let banded: number;
  switch (decision) {
    case "auto_approve": // genuine band: [genuine, 100]
      banded = Math.max(trust, TRUST_THRESHOLDS.genuine);
      break;
    case "human_review": // review band: [review, genuine-1]
      banded = clamp(trust, TRUST_THRESHOLDS.review, TRUST_THRESHOLDS.genuine - 1);
      break;
    case "auto_reject": // high-risk band: [0, review-1]
      banded = Math.min(trust, TRUST_THRESHOLDS.review - 1);
      break;
    default:
      banded = trust;
  }
  return clamp(banded, DISPLAY_FLOOR, DISPLAY_CEIL);
}

/** Confidence proxy: the contract has none, so derive it from how far the
 *  authenticity score sits from the undecided midpoint (50). */
function confidenceFor(authScore: number): number {
  const d = Math.abs(clamp(authScore, 0, 100) - 50) / 50; // 0..1
  return Math.round((0.6 + 0.39 * d) * 100) / 100;
}

// ── Signals ──────────────────────────────────────────────────────────────────

const FORENSIC_HINTS = [
  "ela",
  "compression",
  "font",
  "metadata",
  "signature",
  "qr",
  "pixel",
  "noise",
  "copy-move",
  "copy move",
  "tamper",
  "edited",
  "edit",
  "re-save",
  "resave",
  "scan",
  "c2pa",
  "provenance",
  "object stream",
  "exif",
  "ghost",
  "cfa",
  "splice",
  "inpaint",
  "synthetic",
  "ai-generat",
];

function severityForVerdict(verdict: Verdict): Severity {
  if (verdict === "high_risk") return "high";
  if (verdict === "review") return "medium";
  return "info";
}

function familyForReason(reason: string): { family: SignalFamily; pipeline: 1 | 2 } {
  const r = reason.toLowerCase();
  if (/signature|qr|c2pa|provenance|digilocker/.test(r))
    return { family: "provenance", pipeline: 1 };
  if (/metadata|object stream|producer|creationdate|moddate|font/.test(r))
    return { family: "structure", pipeline: 1 };
  if (FORENSIC_HINTS.some((h) => r.includes(h)))
    return { family: "image", pipeline: 1 };
  if (/across|cross-doc|cross doc|reconcile|does not match the|mismatch across/.test(r))
    return { family: "triangulation", pipeline: 2 };
  return { family: "content", pipeline: 2 };
}

function fieldVerificationSignal(
  fv: BackendFieldVerification
): Signal {
  switch (fv.status) {
    case "verified":
      return {
        family: "content",
        label: "Fields match issuer record",
        severity: "info",
        reason: `All checked fields match the ${fv.issuer} record of authority.`,
        region: null,
      };
    case "mismatch":
      return {
        family: "content",
        label: "Field mismatch vs issuer record",
        severity: "high",
        reason: `One or more fields disagree with the ${fv.issuer} record of authority.`,
        region: null,
      };
    default:
      return {
        family: "content",
        label: "Could not verify against issuer",
        severity: "medium",
        reason: `No authoritative ${fv.issuer} record was available to verify against; treat as unverified, not as proof of fraud.`,
        region: null,
      };
  }
}

// ── Extracted fields ──────────────────────────────────────────────────────────

const FIELD_LABELS: Record<string, string> = {
  pan: "PAN",
  name: "Name",
  assessment_year: "Assessment year",
  gross_total_income: "Gross total income",
  total_tax_paid: "Total tax paid",
  acknowledgement_number: "Acknowledgement no.",
  employer_name: "Employer",
  owner_name: "Owner name",
  survey_number: "Survey number",
  area_hectare: "Area (ha)",
  village: "Village",
  district: "District",
  taluka: "Taluka",
  state: "State",
  parcel_id: "Parcel ID (ULPIN)",
  encumbrance: "Encumbrance",
};

function prettyField(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// ── Per-document mapping ──────────────────────────────────────────────────────

export interface DocInput {
  resp: BackendVerifyResponse;
  filename: string;
  docType: DocType;
  /** Object-URL preview of the uploaded file, or null (placeholder is used). */
  thumbnailUrl: string | null;
  index: number;
  /** Real extracted field values (from the batch endpoint), if available. */
  extractedFields?: Record<string, unknown>;
}

function resolveHeatmap(url: string | null, apiBase: string): string | null {
  if (!url) return null;
  if (/^(https?:|data:)/.test(url)) return url;
  return `${apiBase.replace(/\/$/, "")}${url.startsWith("/") ? "" : "/"}${url}`;
}

function mapDocument(input: DocInput, apiBase: string): DocumentResult {
  const { resp, filename, docType, thumbnailUrl } = input;
  const verdict = decisionToVerdict(resp.decision);
  const trustScore = toTrustScore(resp.decision, resp.risk_score);
  const sev = severityForVerdict(verdict);

  // Route each backend `reason` string to the pipeline it most likely came from.
  const p1Signals: Signal[] = [];
  const p2Signals: Signal[] = [];
  for (const reason of resp.reasons ?? []) {
    const { family, pipeline } = familyForReason(reason);
    const signal: Signal = {
      family,
      label: reason.length > 64 ? reason.slice(0, 61) + "…" : reason,
      severity: sev,
      reason,
      region: null,
    };
    (pipeline === 1 ? p1Signals : p2Signals).push(signal);
  }

  // The field-verification verdict is the core Pipeline-2 output — always show it.
  p2Signals.push(fieldVerificationSignal(resp.field_verification));

  const heatmap = resolveHeatmap(resp.heatmap_url, apiBase);
  if (heatmap) {
    p1Signals.push({
      family: "image",
      label: "Forensic heatmap available",
      severity: sev,
      reason:
        "Pixel-level forensics localised a region of interest; see the heatmap overlay.",
      region: null,
    });
  }

  // Recovered before/after PDF-revision evidence (the killer edited-PDF signal).
  const revisionEvidence: RevisionEvidence | null =
    resp.revision_evidence && resp.revision_evidence.detected
      ? {
          detected: true,
          summary: resp.revision_evidence.summary ?? null,
          changes: (resp.revision_evidence.changes ?? []).map((c) => ({
            field_hint: c.field_hint ?? null,
            original_value: c.original_value,
            current_value: c.current_value,
            kind: (["identifier", "amount", "date", "name", "text"].includes(c.kind)
              ? c.kind
              : "text") as RevisionEvidence["changes"][number]["kind"],
            weight: (["high", "medium", "low"].includes(c.weight)
              ? c.weight
              : "low") as RevisionEvidence["changes"][number]["weight"],
            page_number: c.page_number ?? 0,
            bbox: c.bbox ?? null,
          })),
        }
      : null;

  if (revisionEvidence) {
    for (const c of revisionEvidence.changes) {
      const hint = c.field_hint ? `${c.field_hint} — ` : "";
      p1Signals.unshift({
        family: "structure",
        label: "Edited PDF revision recovered",
        severity: c.weight === "high" ? "high" : "medium",
        reason: `${hint}original: ${c.original_value} → edited: ${c.current_value}. The prior revision is still embedded in the PDF (incremental-update edit).`,
        region: null,
      });
    }
  }

  // Extracted-fields table. The async batch endpoint returns real extracted
  // VALUES, so prefer those; fall back to matched field names otherwise.
  const matched = new Set(resp.field_verification.matched_fields ?? []);
  let extracted: ExtractedField[];
  if (input.extractedFields && Object.keys(input.extractedFields).length > 0) {
    const fvStatus = resp.field_verification.status;
    extracted = Object.entries(input.extractedFields).map(([k, v]) => {
      let status: ExtractedField["status"] = "ok";
      if (!matched.has(k)) status = fvStatus === "mismatch" ? "mismatch" : "ok";
      return {
        key: prettyField(k),
        value: v === null || v === undefined || v === "" ? "—" : String(v),
        status,
      };
    });
  } else {
    extracted = (resp.field_verification.matched_fields ?? []).map((f) => ({
      key: prettyField(f),
      value: "Matched issuer record",
      status: "ok" as const,
    }));
  }

  const isPdf = /\.pdf$/i.test(filename);
  return {
    doc_id: `doc_${input.index}`,
    filename,
    doc_type: docType,
    // Cards use a clean placeholder for PDFs; images use their real preview.
    thumbnail_url: isPdf ? docPlaceholder(docType) : (thumbnailUrl ?? docPlaceholder(docType)),
    // The viewer loads the actual uploaded file (image or PDF) from here.
    preview_url: thumbnailUrl ?? null,
    trust_score: trustScore,
    verdict,
    pipeline1: {
      score: trustScore,
      heatmap_url: heatmap,
      signals: p1Signals,
    },
    pipeline2: {
      score: trustScore,
      extracted_fields: extracted,
      signals: p2Signals,
    },
    revision_evidence: revisionEvidence,
  };
}

// ── Application-level assembly ────────────────────────────────────────────────

export interface BuildResultArgs {
  applicationId: string;
  submittedAt: string; // ISO
  docs: DocInput[];
  apiBase: string;
}

function buildOverall(docs: DocInput[]): OverallResult {
  // Worst decision wins; authenticity is the weakest link across documents.
  let worst: string = "auto_approve";
  let minAuth = 100;
  for (const d of docs) {
    if ((DECISION_RANK[d.resp.decision] ?? 2) > (DECISION_RANK[worst] ?? 0)) {
      worst = d.resp.decision;
    }
    minAuth = Math.min(minAuth, d.resp.risk_score);
  }

  const verdict = decisionToVerdict(worst);
  const n = docs.length;
  const flagged = docs.filter((d) => d.resp.decision !== "auto_approve").length;
  const topReason = docs
    .find((d) => d.resp.decision === worst)
    ?.resp.reasons?.[0];

  let summary: string;
  if (worst === "auto_approve") {
    summary = `All ${n} document${n === 1 ? "" : "s"} are consistent with issuer records and show no tampering signals.`;
  } else if (worst === "human_review") {
    summary = `${flagged} of ${n} document${n === 1 ? "" : "s"} need a closer look before a decision can be made.`;
  } else {
    summary = `${flagged} of ${n} document${n === 1 ? "" : "s"} show strong fraud signals; rejection is recommended pending review.`;
  }
  if (topReason) summary += ` Key signal: ${topReason}`;

  return {
    trust_score: toTrustScore(worst, minAuth),
    verdict,
    confidence: confidenceFor(minAuth),
    summary,
  };
}

export function buildVerificationResult(args: BuildResultArgs): VerificationResult {
  const documents = args.docs.map((d) => mapDocument(d, args.apiBase));
  return {
    application_id: args.applicationId,
    submitted_at: args.submittedAt,
    overall: buildOverall(args.docs),
    documents,
    // The frozen per-call /verify contract carries no cross-document report,
    // so this stays empty until a dedicated cross-doc endpoint is exposed.
    cross_document: [],
    flag_history_notes: [],
  };
}

// ── Async batch endpoint (POST /verify/batch) ─────────────────────────────────

export interface BackendBatchDocument extends BackendVerifyResponse {
  filename: string;
  document_type: string;
  extracted_fields?: Record<string, unknown>;
}

export interface BackendBatchOverall {
  risk_score: number; // authenticity
  route_taken: string;
  decision: BackendDecision | string;
  reasons: string[];
}

export interface BackendCrossSignal {
  label: string;
  reason: string;
  severity: string;
}

export interface BackendBatchJob {
  job_id: string;
  status: "processing" | "done" | "error" | string;
  progress: number;
  applicant_id: string;
  submitted_at: string;
  document_count: number;
  documents: BackendBatchDocument[];
  cross_document: BackendCrossSignal[];
  overall: BackendBatchOverall | null;
  error: string | null;
  underwriter_decision?: string | null;
}

const VALID_SEVERITY: Severity[] = ["info", "low", "medium", "high"];

function coerceDocType(t: string): DocType {
  const known: DocType[] = [
    "bank_statement",
    "land_record",
    "itr",
    "salary_slip",
    "unknown",
  ];
  return (known as string[]).includes(t) ? (t as DocType) : "unknown";
}

function coerceSeverity(s: string): Severity {
  return (VALID_SEVERITY as string[]).includes(s) ? (s as Severity) : "medium";
}

function overallFromBackend(
  overall: BackendBatchOverall,
  docCount: number
): OverallResult {
  const verdict = decisionToVerdict(overall.decision);
  let summary: string;
  if (verdict === "genuine") {
    summary = `All ${docCount} document${docCount === 1 ? "" : "s"} are consistent with issuer records and show no tampering signals.`;
  } else if (verdict === "review") {
    summary = `This application needs a closer look before a decision can be made.`;
  } else {
    summary = `Strong fraud signals detected across the application; rejection is recommended pending review.`;
  }
  if (overall.reasons?.[0]) summary += ` Key signal: ${overall.reasons[0]}`;

  return {
    trust_score: toTrustScore(overall.decision, overall.risk_score),
    verdict,
    confidence: confidenceFor(overall.risk_score),
    summary,
  };
}

export function buildResultFromBatch(
  job: BackendBatchJob,
  apiBase: string,
  thumbnails: (string | null)[] = []
): VerificationResult {
  const documents = job.documents.map((d, i) =>
    mapDocument(
      {
        resp: d,
        filename: d.filename,
        docType: coerceDocType(d.document_type),
        thumbnailUrl: thumbnails[i] ?? null,
        index: i,
        extractedFields: d.extracted_fields,
      },
      apiBase
    )
  );

  const overall: OverallResult = job.overall
    ? overallFromBackend(job.overall, documents.length)
    : {
        trust_score: 50,
        verdict: "review",
        confidence: 0.6,
        summary: "Verification could not be completed.",
      };

  const ud = job.underwriter_decision;
  const underwriter_decision =
    ud === "approved" || ud === "review" || ud === "rejected" ? ud : null;

  return {
    application_id: job.applicant_id,
    submitted_at: job.submitted_at,
    overall,
    documents,
    cross_document: (job.cross_document ?? []).map((c) => ({
      label: c.label,
      reason: c.reason,
      severity: coerceSeverity(c.severity),
    })),
    flag_history_notes: [],
    underwriter_decision,
  };
}
