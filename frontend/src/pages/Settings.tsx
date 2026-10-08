import { useEffect, useState } from "react";
import { Moon, Sun, Server, CircleUserRound } from "lucide-react";
import { useTheme } from "@/app/theme";

export function Settings() {
  const { theme, toggle } = useTheme();
  const [health, setHealth] = useState<{status:string; model_configured:boolean} | null>(null);
  useEffect(() => { fetch(`${import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}/health`).then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(setHealth).catch(() => setHealth({status:"unreachable",model_configured:false})); }, []);
  const apiBase =
    import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          Settings
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Profile and application preferences.
        </p>
      </header>

      <section className="card p-5">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">
          Profile
        </h2>
        <div className="mt-4 flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-teal-50 text-pipeline1 dark:bg-pipeline1-softdark dark:text-teal-200">
            <CircleUserRound className="h-7 w-7" />
          </span>
          <div>
            <p className="font-semibold text-slate-800 dark:text-slate-100">
              Loan Officer
            </p>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Underwriting · Demo account
            </p>
          </div>
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">
          Appearance
        </h2>
        <div className="mt-4 flex items-center justify-between">
          <div>
            <p className="font-medium text-slate-800 dark:text-slate-100">
              Theme
            </p>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Light is recommended for reading documents.
            </p>
          </div>
          <button onClick={toggle} className="btn-secondary">
            {theme === "dark" ? (
              <>
                <Sun className="h-4 w-4" /> Light
              </>
            ) : (
              <>
                <Moon className="h-4 w-4" /> Dark
              </>
            )}
          </button>
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">
          Backend
        </h2>
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3 dark:bg-slate-800/60">
            <span className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <Server className="h-4 w-4 text-pipeline1" />
              {health?.status === "ok" ? "Backend reachable" : health ? "Backend unreachable" : "Checking backend…"}
            </span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800">
              {apiBase}
            </code>
          </div>
          <p className="text-xs text-slate-500">Model configuration: {health ? health.model_configured ? "present (live connection checked during analysis)" : "not configured" : "checking"}. Reference records are local / synthetic.</p>
          <p className="text-xs text-slate-400">
            Point the app at a different host by setting{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">
              VITE_API_BASE_URL
            </code>{" "}
            in your <code>.env</code>, then restart the dev server.
          </p>
        </div>
      </section>
    </div>
  );
}
