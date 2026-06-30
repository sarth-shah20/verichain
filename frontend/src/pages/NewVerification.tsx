import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { X, Loader2, ShieldCheck } from "lucide-react";
import { api } from "@/api";
import type { DocType, SubmitFile } from "@/api/types";
import { FileDropzone } from "@/components/FileDropzone";
import { DocTypeIcon } from "@/components/DocTypeIcon";
import { useToast } from "@/app/toast";
import { DOC_TYPE_LABELS, docTypeLabel, formatBytes } from "@/lib/format";

interface QueuedFile {
  id: string;
  file: File;
  docType: DocType;
}

const DOC_TYPE_OPTIONS = Object.keys(DOC_TYPE_LABELS) as DocType[];

export function NewVerification() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [applicationId, setApplicationId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const addFiles = (files: File[]) => {
    setQueue((prev) => [
      ...prev,
      ...files.map((file) => ({
        id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 7)}`,
        file,
        docType: "unknown" as DocType,
      })),
    ]);
  };

  const removeFile = (id: string) =>
    setQueue((prev) => prev.filter((q) => q.id !== id));

  const setType = (id: string, docType: DocType) =>
    setQueue((prev) => prev.map((q) => (q.id === id ? { ...q, docType } : q)));

  const submit = async () => {
    if (queue.length === 0) return;
    setSubmitting(true);
    try {
      const payload: SubmitFile[] = queue.map((q) => ({
        file: q.file,
        doc_type: q.docType,
      }));
      const { job_id } = await api.submit({
        files: payload,
        application_id: applicationId.trim() || undefined,
      });
      navigate(`/processing/${job_id}`);
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Could not submit documents.",
        "warning"
      );
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          New verification
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Upload an applicant's documents to check them for tampering, forgery
          and content mismatches.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <FileDropzone
            onFiles={addFiles}
            onReject={(msg) => toast(msg, "warning")}
          />

          {queue.length === 0 ? (
            <p className="text-center text-sm text-slate-400">
              No documents queued yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {queue.map((q) => (
                <li
                  key={q.id}
                  className="card flex flex-wrap items-center gap-3 p-3"
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
                    <DocTypeIcon type={q.docType} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {q.file.name}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {formatBytes(q.file.size)} ·{" "}
                      {q.file.type.split("/")[1]?.toUpperCase() || "FILE"}
                    </p>
                  </div>
                  <label className="sr-only" htmlFor={`type-${q.id}`}>
                    Document type for {q.file.name}
                  </label>
                  <select
                    id={`type-${q.id}`}
                    value={q.docType}
                    onChange={(e) => setType(q.id, e.target.value as DocType)}
                    className="input w-auto py-1.5 text-xs"
                  >
                    {DOC_TYPE_OPTIONS.map((t) => (
                      <option key={t} value={t}>
                        {docTypeLabel(t)}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => removeFile(q.id)}
                    className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-risk-high dark:hover:bg-slate-800"
                    aria-label={`Remove ${q.file.name}`}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <aside className="space-y-5">
          <div className="card space-y-4 p-5">
            <div>
              <label
                htmlFor="app-id"
                className="block text-sm font-semibold text-slate-700 dark:text-slate-200"
              >
                Application ID{" "}
                <span className="font-normal text-slate-400">(optional)</span>
              </label>
              <input
                id="app-id"
                value={applicationId}
                onChange={(e) => setApplicationId(e.target.value)}
                placeholder="e.g. APP-10231"
                className="input mt-1.5"
              />
            </div>

            <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
              <p className="flex items-center gap-1.5 font-semibold text-slate-600 dark:text-slate-300">
                <ShieldCheck className="h-4 w-4 text-pipeline1" />
                Two pipelines run on every file
              </p>
              <p className="mt-1.5">
                <span className="font-medium text-pipeline1">Forensics</span>{" "}
                checks if the file is physically genuine.{" "}
                <span className="font-medium text-pipeline2">Verification</span>{" "}
                reads and cross-validates the data.
              </p>
            </div>

            <button
              onClick={submit}
              disabled={queue.length === 0 || submitting}
              className="btn-primary w-full"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Submitting…
                </>
              ) : (
                <>Verify {queue.length > 0 ? `${queue.length} ` : ""}document
                {queue.length === 1 ? "" : "s"}</>
              )}
            </button>
            {queue.length === 0 && (
              <p className="text-center text-xs text-slate-400">
                Add at least one valid file to continue.
              </p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
