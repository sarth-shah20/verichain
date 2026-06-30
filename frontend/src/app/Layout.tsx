import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  ShieldCheck,
  FilePlus2,
  History as HistoryIcon,
  Settings,
  Moon,
  Sun,
  CircleUserRound,
} from "lucide-react";
import { useTheme } from "./theme";
import { cx } from "@/lib/format";

const NAV = [
  { to: "/new", label: "New Verification", icon: FilePlus2 },
  { to: "/history", label: "History", icon: HistoryIcon },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Layout() {
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 dark:bg-slate-950 lg:flex-row">
      {/* Sidebar (desktop) / top bar (mobile) */}
      <aside className="flex shrink-0 flex-col border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:w-64 lg:border-b-0 lg:border-r">
        <button
          onClick={() => navigate("/new")}
          className="flex items-center gap-2.5 px-5 py-4 text-left"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-pipeline1 text-white">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <span>
            <span className="block text-lg font-extrabold leading-none tracking-tight text-slate-900 dark:text-white">
              VeriChain
            </span>
            <span className="block text-[11px] font-medium text-slate-400">
              Document verification
            </span>
          </span>
        </button>

        <nav className="flex gap-1 px-3 pb-3 lg:mt-2 lg:flex-col lg:gap-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cx(
                  "flex flex-1 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors lg:flex-none",
                  isActive
                    ? "bg-teal-50 text-pipeline1 dark:bg-pipeline1-softdark dark:text-teal-200"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                )
              }
            >
              <item.icon className="h-5 w-5" />
              <span className="hidden sm:inline">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto hidden items-center justify-between border-t border-slate-200 px-4 py-3 dark:border-slate-800 lg:flex">
          <span className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <CircleUserRound className="h-5 w-5 text-slate-400" />
            Officer
          </span>
          <button
            onClick={toggle}
            className="btn-ghost px-2 py-2"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </button>
        </div>
      </aside>

      {/* Mobile theme toggle */}
      <button
        onClick={toggle}
        className="btn-ghost fixed right-3 top-3 z-30 px-2 py-2 lg:hidden"
        aria-label="Toggle theme"
      >
        {theme === "dark" ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        )}
      </button>

      <main className="flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
