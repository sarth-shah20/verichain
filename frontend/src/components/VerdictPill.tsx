import { CheckCircle2, AlertTriangle, ShieldAlert } from "lucide-react";
import type { Verdict } from "@/api/types";
import { verdictMeta } from "@/lib/risk";
import { cx } from "@/lib/format";

const ICONS: Record<Verdict, typeof CheckCircle2> = {
  genuine: CheckCircle2,
  review: AlertTriangle,
  high_risk: ShieldAlert,
};

const CLASSES: Record<Verdict, string> = {
  genuine:
    "bg-green-50 text-green-700 ring-green-600/20 dark:bg-green-950 dark:text-green-300 dark:ring-green-500/30",
  review:
    "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-500/30",
  high_risk:
    "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-950 dark:text-red-300 dark:ring-red-500/30",
};

export function VerdictPill({
  verdict,
  size = "md",
}: {
  verdict: Verdict;
  size?: "sm" | "md";
}) {
  const Icon = ICONS[verdict];
  const meta = verdictMeta(verdict);
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full font-semibold ring-1 ring-inset",
        CLASSES[verdict],
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm"
      )}
    >
      <Icon className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} />
      {meta.label}
    </span>
  );
}
