import { Scale, AlertTriangle } from "lucide-react";

interface Row { label: string; annual: number }

function toNumber(v: unknown): number | null {
  if (v == null) return null;
  const s = String(v).replace(/[^0-9.]/g, "");
  const n = Number(s);
  return isFinite(n) && n > 0 ? n : null;
}

function findAnnual(doc: { pipeline2: { extracted_fields: { key: string; value: string }[] }; doc_type: string; filename: string }): Row | null {
  const f = doc.pipeline2.extracted_fields;
  // Match monthly gross of a payslip (gross_pay/gross_salary) or annual gross of an ITR.
  const annual = f.find((x) => /(gross.*total|annual|total\s*income)/i.test(x.key));
  const gross = f.find((x) => /(gross\s*pay|gross\s*salary|basic\s*pay)/i.test(x.key));
  let val: number | null = null;
  if (annual) { val = toNumber(annual.value); }
  else if (gross) { const m = toNumber(gross.value); if (m) { val = m * 12; } }
  if (val) return { label: doc.filename.length > 22 ? doc.filename.slice(0, 20) + "…" : doc.filename, annual: val };
  return null;
}

export function IncomeReconcileCard({ documents }: { documents: any[] }) {
  const rows = documents.map(findAnnual).filter(Boolean) as Row[];
  if (rows.length < 2) return null;
  const vals = rows.map((r) => r.annual);
  const max = Math.max(...vals);
  const min = Math.min(...vals);
  const gap = max > 0 ? (max - min) / max : 0;
  const incongruous = gap > 0.15;
  return (
    <section className={`card border-l-4 p-5 ${incongruous ? "border-l-risk-high" : "border-l-risk-low"}`}>
      <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-slate-400">
        {incongruous ? <AlertTriangle className="h-4 w-4 text-risk-high" /> : <Scale className="h-4 w-4 text-risk-low" />}
        Income reconciliation
      </h2>
      <div className="mt-3 space-y-2">
        {rows.map((r, i) => (
          <div key={i}>
            <div className="flex justify-between text-xs text-slate-400">
              <span>{r.label}</span>
              <span className="tnum font-semibold text-slate-200">₹{Math.round(r.annual).toLocaleString("en-IN")}/yr</span>
            </div>
            <div className="mt-1 h-2 rounded bg-slate-800">
              <div className="h-2 rounded bg-teal-500" style={{ width: `${(r.annual / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      {incongruous && (
        <p className="mt-3 text-xs font-semibold text-red-400">⚠️ Annualised incomes diverge by {(gap * 100).toFixed(0)}% — inspect before approving.</p>
      )}
    </section>
  );
}
