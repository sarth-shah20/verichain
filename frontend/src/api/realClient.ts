import type {
  HistoryItem,
  JobStatusResponse,
  SubmitOptions,
  SubmitResponse,
  UnderwriterDecision,
  VeriChainApi,
  VerificationResult,
} from "./types";
import {
  buildResultFromBatch,
  decisionToVerdict,
  toTrustScore,
  type BackendBatchJob,
} from "./adapter";

/** One row from GET /verifications (the persistent history list). */
interface BackendHistoryRow {
  job_id: string;
  applicant_id: string;
  submitted_at: string;
  doc_names: string | null;
  document_count: number;
  decision: string;
  risk_score: number;
  underwriter_decision: string | null;
}

// ---------------------------------------------------------------------------
// Real HTTP client — drives the backend's ASYNC BATCH contract:
//
//   POST /verify/batch            -> { job_id }            (returns immediately)
//   GET  /verify/batch/{job_id}   -> { status, progress, overall, documents,
//                                      cross_document }     (poll until done)
//
// The whole applicant file is submitted at once, so the backend can run
// cross-document checks (income on the salary slip vs. the ITR) that a single
// /verify call can't. Job state lives server-side, so a results page survives
// reload. The frozen single-doc /verify contract is left untouched.
//
// Base URL comes from VITE_API_BASE_URL. See api/index.ts.
// ---------------------------------------------------------------------------

interface LocalJob {
  thumbnails: (string | null)[]; // object-URL previews, by document index
  objectUrls: string[]; // tracked for potential revocation
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = reader.result as string;
      const comma = res.indexOf(","); // strip "data:<mime>;base64,"
      resolve(comma >= 0 ? res.slice(comma + 1) : res);
    };
    reader.onerror = () => reject(reader.error ?? new Error("File read failed"));
    reader.readAsDataURL(file);
  });
}

export class RealVeriChainApi implements VeriChainApi {
  /** Client-side context the backend doesn't hold (thumbnails) + submit order. */
  private readonly localJobs = new Map<string, LocalJob>();
  private readonly order: string[] = [];

  constructor(private readonly baseUrl: string) {}

  private url(path: string): string {
    return `${this.baseUrl.replace(/\/$/, "")}${path}`;
  }

  private async fetchJob(jobId: string): Promise<BackendBatchJob> {
    // no-store: the poll must always see fresh job state. Without this the
    // browser can replay a cached early "processing" response and the UI gets
    // stuck at 100% even though the job is already "done".
    const res = await fetch(this.url(`/verify/batch/${encodeURIComponent(jobId)}`), {
      cache: "no-store",
    });
    if (res.status === 404) {
      throw new Error("Job not found — it may have expired. Start a new verification.");
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${text || res.statusText}`);
    }
    return (await res.json()) as BackendBatchJob;
  }

  private thumbsFor(jobId: string): (string | null)[] {
    return this.localJobs.get(jobId)?.thumbnails ?? [];
  }

  async submit(options: SubmitOptions): Promise<SubmitResponse> {
    const documents = await Promise.all(
      options.files.map(async (sf) => ({
        document_type: sf.doc_type ?? "unknown",
        file_base64: await readFileAsBase64(sf.file),
        filename: sf.file.name,
      }))
    );

    // Real previews for BOTH image and PDF uploads (PDFs render in an iframe in
    // the viewer; cards still use a placeholder thumbnail — see adapter).
    const thumbnails = options.files.map((sf) =>
      sf.file.type.startsWith("image/") || sf.file.type === "application/pdf"
        ? URL.createObjectURL(sf.file)
        : null
    );

    const res = await fetch(this.url("/verify/batch"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        applicant_id: options.application_id?.trim() || undefined,
        documents,
      }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Submit failed (${res.status}): ${text || res.statusText}`);
    }
    const { job_id } = (await res.json()) as { job_id: string };

    this.localJobs.set(job_id, {
      thumbnails,
      objectUrls: thumbnails.filter((u): u is string => !!u),
    });
    this.order.unshift(job_id);

    return { job_id };
  }

  async getStatus(jobId: string): Promise<JobStatusResponse> {
    const job = await this.fetchJob(jobId);
    if (job.status === "done") {
      return {
        job_id: jobId,
        status: "done",
        progress: 100,
        document_stages: job.document_stages,
        result: buildResultFromBatch(job, this.baseUrl, this.thumbsFor(jobId)),
      };
    }
    if (job.status === "error") {
      return { job_id: jobId, status: "error", progress: 100, result: null, error: job.error };
    }
    return {
      job_id: jobId,
      status: "processing",
      progress: job.progress ?? 0,
      document_stages: job.document_stages,
      result: null,
    };
  }

  async getResult(jobId: string): Promise<VerificationResult> {
    const job = await this.fetchJob(jobId);
    if (job.status === "error") throw new Error(job.error ?? "Verification failed.");
    if (job.status !== "done") throw new Error("Job still processing.");
    return buildResultFromBatch(job, this.baseUrl, this.thumbsFor(jobId));
  }

  async getHistory(): Promise<HistoryItem[]> {
    // Persistent, server-side history — survives restart / new session.
    const res = await fetch(this.url("/verifications"), { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${text || res.statusText}`);
    }
    const rows = (await res.json()) as BackendHistoryRow[];
    const ud = (v: string | null): UnderwriterDecision | null =>
      v === "approved" || v === "review" || v === "rejected" ? v : null;
    return rows.map((r) => ({
      job_id: r.job_id,
      application_id: r.applicant_id,
      submitted_at: r.submitted_at,
      document_count: r.document_count,
      doc_names: r.doc_names ?? undefined,
      // Map through the same functions the rest of the UI uses so the verdict
      // and (clamped) trust score are identical to the report view.
      verdict: decisionToVerdict(r.decision),
      trust_score: toTrustScore(r.decision, r.risk_score),
      underwriter_decision: ud(r.underwriter_decision),
    }));
  }

  async recordDecision(jobId: string, decision: UnderwriterDecision, note?: string | null): Promise<void> {
    const res = await fetch(this.url(`/verify/batch/${encodeURIComponent(jobId)}/decision`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note: note ?? undefined }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Could not record decision (${res.status}): ${text || res.statusText}`);
    }
  }

  async deleteVerification(jobId: string): Promise<void> {
    const res = await fetch(this.url(`/verifications/${encodeURIComponent(jobId)}`), {
      method: "DELETE",
    });
    if (!res.ok && res.status !== 404) {
      const text = await res.text().catch(() => "");
      throw new Error(`Could not delete (${res.status}): ${text || res.statusText}`);
    }
  }
}
