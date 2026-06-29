import type {
  HistoryItem,
  JobStatusResponse,
  SubmitOptions,
  SubmitResponse,
  VeriChainApi,
  VerificationResult,
} from "./types";
import { buildResultFromBatch, type BackendBatchJob } from "./adapter";

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
// Activated by VITE_USE_MOCK=false (+ VITE_API_BASE_URL). See api/index.ts.
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
    const res = await fetch(this.url(`/verify/batch/${encodeURIComponent(jobId)}`));
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

    // Real previews for image uploads; PDFs fall back to a placeholder downstream.
    const thumbnails = options.files.map((sf) =>
      sf.file.type.startsWith("image/") ? URL.createObjectURL(sf.file) : null
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
        result: buildResultFromBatch(job, this.baseUrl, this.thumbsFor(jobId)),
      };
    }
    if (job.status === "error") {
      return { job_id: jobId, status: "error", progress: 100, result: null };
    }
    return {
      job_id: jobId,
      status: "processing",
      progress: job.progress ?? 0,
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
    // The contract exposes per-applicant audit history but no "list all"; the
    // dashboard history is this session's batch jobs, read back from the server.
    const ids = this.order.length ? this.order : [...this.localJobs.keys()];
    const settled = await Promise.allSettled(ids.map((id) => this.fetchJob(id)));

    const items: HistoryItem[] = [];
    for (const s of settled) {
      if (s.status !== "fulfilled" || s.value.status !== "done") continue;
      const job = s.value;
      const result = buildResultFromBatch(job, this.baseUrl, this.thumbsFor(job.job_id));
      items.push({
        job_id: job.job_id,
        application_id: result.application_id,
        submitted_at: result.submitted_at,
        document_count: result.documents.length,
        verdict: result.overall.verdict,
        risk_score: result.overall.risk_score,
      });
    }
    return items.sort((a, b) => b.submitted_at.localeCompare(a.submitted_at));
  }
}
