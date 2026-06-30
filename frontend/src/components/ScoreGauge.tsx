import { colorForScore, verdictForScore, verdictMeta } from "@/lib/risk";
import { cx } from "@/lib/format";

interface ScoreGaugeProps {
  score: number; // 0–100
  size?: number;
  strokeWidth?: number;
  label?: string;
  showVerdict?: boolean;
}

/**
 * Circular trust gauge. Higher score = more genuine. Color follows the trust
 * scale; a text label is always shown so meaning never relies on color alone.
 */
export function ScoreGauge({
  score,
  size = 160,
  strokeWidth = 12,
  label = "Trust score",
  showVerdict = true,
}: ScoreGaugeProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  const color = colorForScore(clamped);
  const meta = verdictMeta(verdictForScore(clamped));

  return (
    <div
      className="inline-flex flex-col items-center"
      role="img"
      aria-label={`${label}: ${clamped} out of 100, ${meta.label}`}
    >
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={strokeWidth}
            className="stroke-slate-200 dark:stroke-slate-800"
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            style={{ transition: "stroke-dasharray 0.8s ease, stroke 0.4s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="tnum text-4xl font-extrabold leading-none"
            style={{ color }}
          >
            {clamped}
          </span>
          <span className="mt-1 text-xs font-medium uppercase tracking-wide text-slate-400">
            / 100
          </span>
        </div>
      </div>
      {showVerdict && (
        <span
          className={cx(
            "mt-3 text-sm font-semibold",
            meta.tone === "green" && "text-risk-low",
            meta.tone === "amber" && "text-risk-mid",
            meta.tone === "red" && "text-risk-high"
          )}
        >
          {meta.label}
        </span>
      )}
    </div>
  );
}
