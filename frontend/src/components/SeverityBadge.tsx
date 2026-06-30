import type { Severity } from "@/api/types";
import { SEVERITY_META } from "@/lib/risk";
import { cx } from "@/lib/format";

export function SeverityBadge({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold",
        meta.classes
      )}
    >
      <span
        aria-hidden
        className={cx(
          "h-1.5 w-1.5 rounded-full",
          severity === "high" && "bg-red-500",
          severity === "medium" && "bg-amber-500",
          severity === "low" && "bg-sky-500",
          severity === "info" && "bg-slate-400"
        )}
      />
      {meta.label}
    </span>
  );
}
