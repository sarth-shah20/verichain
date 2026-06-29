import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ShieldCheck, ScanText, GitMerge, Check, Loader2 } from "lucide-react";
import { api } from "@/api";
import { useStore } from "@/app/store";
import { ErrorState } from "@/components/States";
import { cx } from "@/lib/format";

const STEPS = [
  {
    icon: ShieldCheck,
    title: "Checking authenticity",
    detail: "Provenance, file & image forensics",
    threshold: 0,
    accent: "text-pipeline1",
  },
  {
    icon: ScanText,
    title: "Extracting & validating content",
    detail: "OCR, field extraction, cross-validation",
    threshold: 40,
    accent: "text-pipeline2",
  },
  {
    icon: GitMerge,
    title: "Fusing results",
    detail: "Merging reports, weighing flag history",
    threshold: 80,
    accent: "text-slate-600 dark:text-slate-300",
  },
];

export function Processing() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { setCurrent } = useStore();
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const status = await api.getStatus(jobId);
        if (cancelled) return;
        setProgress(status.progress);

        if (status.status === "error") {
          setError("The verification job could not be completed.");
          return;
        }
        if (status.status === "done" && status.result) {
          setCurrent(jobId, status.result);
          setProgress(100);
          window.setTimeout(() => {
            if (!cancelled) navigate(`/results/${jobId}`, { replace: true });
          }, 500);
          return;
        }
        timer.current = window.setTimeout(poll, 600);
      } catch {
        if (!cancelled) setError("Lost connection to the verification service.");
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [jobId, navigate, setCurrent]);

  if (error) {
    return (
      <ErrorState
        title="Verification failed"
        description={error}
        onRetry={() => navigate("/new")}
      />
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 py-6">
      <header className="text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-teal-50 text-pipeline1 dark:bg-pipeline1-softdark dark:text-teal-200">
          <Loader2 className="h-7 w-7 animate-spin" />
        </div>
        <h1 className="mt-4 text-2xl font-bold text-slate-900 dark:text-white">
          Verifying documents
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          This usually takes a few seconds. You can stay on this page.
        </p>
      </header>

      <div className="card p-6">
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-200">
            Overall progress
          </span>
          <span className="tnum font-bold text-pipeline1">{progress}%</span>
        </div>
        <div
          className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-pipeline1 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>

        <ol className="mt-6 space-y-4">
          {STEPS.map((step, i) => {
            const next = STEPS[i + 1];
            const done = progress >= (next?.threshold ?? 100);
            const active = progress >= step.threshold && !done;
            return (
              <li key={step.title} className="flex items-start gap-3">
                <span
                  className={cx(
                    "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border",
                    done
                      ? "border-pipeline1 bg-pipeline1 text-white"
                      : active
                        ? "border-pipeline1 text-pipeline1"
                        : "border-slate-200 text-slate-300 dark:border-slate-700"
                  )}
                >
                  {done ? (
                    <Check className="h-4 w-4" />
                  ) : active ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <step.icon className="h-4 w-4" />
                  )}
                </span>
                <div>
                  <p
                    className={cx(
                      "font-semibold",
                      done || active
                        ? "text-slate-800 dark:text-slate-100"
                        : "text-slate-400"
                    )}
                  >
                    {step.title}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {step.detail}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
