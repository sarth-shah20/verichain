import { useCallback, useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cx } from "@/lib/format";

const ACCEPTED = ["application/pdf", "image/jpeg", "image/png"];
const ACCEPTED_LABEL = "PDF, JPG or PNG";
const MAX_BYTES = 25 * 1024 * 1024; // 25 MB

interface FileDropzoneProps {
  onFiles: (files: File[]) => void;
  onReject: (message: string) => void;
}

export function FileDropzone({ onFiles, onReject }: FileDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handle = useCallback(
    (fileList: FileList | null) => {
      if (!fileList || fileList.length === 0) return;
      const accepted: File[] = [];
      const rejected: string[] = [];
      Array.from(fileList).forEach((file) => {
        if (!ACCEPTED.includes(file.type)) {
          rejected.push(`${file.name} — unsupported type`);
        } else if (file.size > MAX_BYTES) {
          rejected.push(`${file.name} — exceeds 25 MB`);
        } else {
          accepted.push(file);
        }
      });
      if (rejected.length) {
        onReject(
          `Rejected ${rejected.length} file(s): ${rejected.join("; ")}. Only ${ACCEPTED_LABEL} up to 25 MB are allowed.`
        );
      }
      if (accepted.length) onFiles(accepted);
    },
    [onFiles, onReject]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handle(e.dataTransfer.files);
      }}
      className={cx(
        "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
        dragging
          ? "border-pipeline1 bg-teal-50/60 dark:bg-pipeline1-softdark/30"
          : "border-slate-300 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-900/40"
      )}
    >
      <div className="rounded-full bg-teal-100 p-3 text-pipeline1 dark:bg-pipeline1-softdark dark:text-teal-200">
        <UploadCloud className="h-7 w-7" />
      </div>
      <p className="mt-4 text-base font-semibold text-slate-800 dark:text-slate-100">
        Drag & drop documents here
      </p>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        {ACCEPTED_LABEL} · up to 25 MB each · multiple files supported
      </p>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="btn-secondary mt-5"
      >
        Browse files
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
        className="sr-only"
        onChange={(e) => {
          handle(e.target.files);
          e.target.value = "";
        }}
        aria-label="Upload documents"
      />
    </div>
  );
}
