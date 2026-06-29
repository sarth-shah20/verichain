import { ShieldCheck, ScanText } from "lucide-react";
import { cx } from "@/lib/format";

type Pipeline = 1 | 2;

/** Small label that color-codes a pipeline (1 = teal authenticity, 2 = indigo content). */
export function PipelineBadge({
  pipeline,
  className,
}: {
  pipeline: Pipeline;
  className?: string;
}) {
  const isOne = pipeline === 1;
  const Icon = isOne ? ShieldCheck : ScanText;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold",
        isOne
          ? "bg-teal-50 text-pipeline1 dark:bg-pipeline1-softdark dark:text-teal-200"
          : "bg-indigo-50 text-pipeline2 dark:bg-pipeline2-softdark dark:text-indigo-200",
        className
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {isOne ? "Pipeline 1 · Authenticity" : "Pipeline 2 · Content"}
    </span>
  );
}
