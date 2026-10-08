import { Check, AlertTriangle, MinusCircle } from "lucide-react";
import type { ExtractedField, FieldStatus } from "@/api/types";
import { cx } from "@/lib/format";

const STATUS_META: Record<
  FieldStatus,
  { icon: typeof Check; label: string; row: string; badge: string }
> = {
  ok: {
    icon: Check,
    label: "Verified",
    row: "",
    badge: "text-risk-low",
  },
  mismatch: {
    icon: AlertTriangle,
    label: "Mismatch",
    row: "bg-red-50/60 dark:bg-red-950/30",
    badge: "text-risk-high",
  },
  missing: {
    icon: MinusCircle,
    label: "Missing",
    row: "bg-amber-50/60 dark:bg-amber-950/30",
    badge: "text-risk-mid",
  },
  unverified: {
    icon: MinusCircle,
    label: "Unverified",
    row: "",
    badge: "text-slate-500",
  },
};

export function FieldsTable({ fields }: { fields: ExtractedField[] }) {
  if (fields.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
        No fields were extracted from this document.
      </p>
    );
  }

  return (
    <div className="overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
            <th className="px-4 py-2 font-semibold">Field</th>
            <th className="px-4 py-2 font-semibold">Value</th>
            <th className="px-4 py-2 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {fields.map((f) => {
            const meta = STATUS_META[f.status];
            const Icon = meta.icon;
            return (
              <tr key={f.key} className={meta.row}>
                <td className="px-4 py-2.5 font-medium text-slate-600 dark:text-slate-300">
                  {f.key}
                </td>
                <td className="tnum break-words max-w-64 px-4 py-2.5 font-semibold text-slate-800 dark:text-slate-100">
                  {f.value}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={cx(
                      "inline-flex items-center gap-1 text-xs font-semibold",
                      meta.badge
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {meta.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
