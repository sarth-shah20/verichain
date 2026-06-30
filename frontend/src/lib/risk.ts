import type { Severity, Verdict } from "@/api/types";

// ---------------------------------------------------------------------------
// Trust / authenticity score (adjustable in one place). HIGHER = MORE genuine.
//   70–100 → green  "Genuine"
//   40–69  → amber  "Needs review"
//   0–39   → red    "High risk / Likely forged"
// ---------------------------------------------------------------------------
export const TRUST_THRESHOLDS = {
  review: 40, // ≥ this → at least review
  genuine: 70, // ≥ this → genuine
} as const;

export function verdictForScore(score: number): Verdict {
  if (score >= TRUST_THRESHOLDS.genuine) return "genuine";
  if (score >= TRUST_THRESHOLDS.review) return "review";
  return "high_risk";
}

export interface VerdictMeta {
  label: string;
  /** Tailwind color family hint used to build classes. */
  tone: "green" | "amber" | "red";
  hex: string;
}

export const VERDICT_META: Record<Verdict, VerdictMeta> = {
  genuine: { label: "Genuine", tone: "green", hex: "#16a34a" },
  review: { label: "Needs review", tone: "amber", hex: "#d97706" },
  high_risk: { label: "High risk", tone: "red", hex: "#dc2626" },
};

export function verdictMeta(verdict: Verdict): VerdictMeta {
  return VERDICT_META[verdict];
}

/** Color for a raw 0–100 score. */
export function colorForScore(score: number): string {
  return VERDICT_META[verdictForScore(score)].hex;
}

export interface SeverityMeta {
  label: string;
  rank: number;
  /** Classes for badge background/text in light + dark. */
  classes: string;
}

export const SEVERITY_META: Record<Severity, SeverityMeta> = {
  info: {
    label: "Info",
    rank: 0,
    classes:
      "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  },
  low: {
    label: "Low",
    rank: 1,
    classes:
      "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  },
  medium: {
    label: "Medium",
    rank: 2,
    classes:
      "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  high: {
    label: "High",
    rank: 3,
    classes: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
  },
};

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low", "info"];

export function severityRank(s: Severity): number {
  return SEVERITY_META[s].rank;
}
