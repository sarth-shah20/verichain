import type {
  HistoryItem,
  JobStatusResponse,
  SubmitOptions,
  SubmitResponse,
  VeriChainApi,
  VerificationResult,
} from "@/api/types";
import { SAMPLE_RESULTS } from "./data";

// ---------------------------------------------------------------------------
// In-memory mock backend. Simulates async job processing with a progress
// ramp, and keeps a small history. Implements the exact VeriChainApi shape.
// ---------------------------------------------------------------------------

interface Job {
  job_id: string;
  startedAt: number;
  durationMs: number;
  result: VerificationResult;
}

const jobs = new Map<string, Job>();

// Seed completed jobs with the three samples so History is populated and the
// seeded results are reachable via deep link (job ids "seed_0".."seed_2").
const completedResults = new Map<string, VerificationResult>();
SAMPLE_RESULTS.forEach((r, i) => completedResults.set(`seed_${i}`, r));

let submitCounter = 0;

function delay(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

export class MockVeriChainApi implements VeriChainApi {
  async submit(options: SubmitOptions): Promise<SubmitResponse> {
    await delay(450);
    const jobId = `job_${Date.now().toString(36)}_${submitCounter}`;

    // Rotate through the three samples so each demo submit tells a story,
    // and reflect the user's application id / filenames into the result.
    const template = SAMPLE_RESULTS[submitCounter % SAMPLE_RESULTS.length];
    submitCounter += 1;

    const result: VerificationResult = {
      ...template,
      application_id:
        options.application_id?.trim() ||
        `APP-${10000 + Math.floor(Math.random() * 9000)}`,
      submitted_at: new Date().toISOString(),
      documents: template.documents.map((doc, idx) => {
        const submitted = options.files[idx];
        return {
          ...doc,
          filename: submitted?.file.name ?? doc.filename,
          doc_type:
            submitted?.doc_type && submitted.doc_type !== "unknown"
              ? submitted.doc_type
              : doc.doc_type,
        };
      }),
    };

    jobs.set(jobId, {
      job_id: jobId,
      startedAt: Date.now(),
      durationMs: 4200,
      result,
    });
    return { job_id: jobId };
  }

  async getStatus(jobId: string): Promise<JobStatusResponse> {
    await delay(120);

    // Already-completed (e.g. history) job.
    if (completedResults.has(jobId)) {
      return {
        job_id: jobId,
        status: "done",
        progress: 100,
        result: completedResults.get(jobId) ?? null,
      };
    }

    const job = jobs.get(jobId);
    if (!job) {
      return { job_id: jobId, status: "error", progress: 0, result: null };
    }

    const elapsed = Date.now() - job.startedAt;
    const progress = Math.min(100, Math.round((elapsed / job.durationMs) * 100));

    if (progress >= 100) {
      completedResults.set(jobId, job.result);
      return { job_id: jobId, status: "done", progress: 100, result: job.result };
    }

    return { job_id: jobId, status: "processing", progress, result: null };
  }

  async getResult(jobId: string): Promise<VerificationResult> {
    const status = await this.getStatus(jobId);
    if (status.status === "done" && status.result) return status.result;
    if (status.status === "error") throw new Error("Job not found");
    throw new Error("Job still processing");
  }

  async getHistory(): Promise<HistoryItem[]> {
    await delay(300);
    const items: HistoryItem[] = [];
    completedResults.forEach((r, jobId) => {
      items.push({
        job_id: jobId,
        application_id: r.application_id,
        submitted_at: r.submitted_at,
        document_count: r.documents.length,
        verdict: r.overall.verdict,
        risk_score: r.overall.risk_score,
      });
    });
    return items.sort(
      (a, b) =>
        new Date(b.submitted_at).getTime() - new Date(a.submitted_at).getTime()
    );
  }
}
