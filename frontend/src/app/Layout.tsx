import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ShieldCheck, Plus, History, Settings, Moon, Sun, LayoutDashboard, ArrowUpRight, ScanLine } from "lucide-react";
import { useTheme } from "./theme";
import { cx } from "@/lib/format";
const navigation = [
  { to: "/queue", label: "Overview", icon: LayoutDashboard },
  { to: "/new", label: "New verification", icon: Plus },
  { to: "/history", label: "Verification history", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];
export function Layout() {
  const { theme, toggle } = useTheme();
  const location = useLocation(); const navigate = useNavigate();
  const section = location.pathname.startsWith("/app/") ? "Evidence workspace" : location.pathname.startsWith("/results") ? "Verification report" : location.pathname.startsWith("/processing") ? "Live analysis" : navigation.find(n => location.pathname.startsWith(n.to))?.label ?? "Workspace";
  return <div className="app-shell">
    <aside className="app-sidebar">
      <button className="brand" onClick={() => navigate("/queue")} aria-label="VeriChain overview"><span className="brand-icon"><ShieldCheck size={24} /></span><span>VeriChain<span className="brand-caption">DOCUMENT INTELLIGENCE</span></span></button>
      <div className="sidebar-label">WORKSPACE</div>
      <nav className="sidebar-nav">{navigation.map(item => <NavLink key={item.to} to={item.to} className={({ isActive }) => cx("sidebar-link", isActive && "active")}><item.icon size={18} /><span>{item.label}</span>{item.to === "/new" && <span className="ml-auto opacity-40"><ArrowUpRight size={14} /></span>}</NavLink>)}</nav>
      <div className="sidebar-project"><ScanLine size={20} className="text-teal-300" /><p>Evidence behind<br /><strong>every decision.</strong></p><span>Built for the TARP course project</span></div>
      <div className="sidebar-profile"><span className="profile-avatar">LO</span><div><strong>Loan officer</strong><span>Review workspace</span></div><button onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} className="sidebar-theme">{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button></div>
    </aside>
    <div className="app-main"><header className="app-topbar"><div><span className="text-slate-400">Workspace</span><span className="mx-3 text-slate-300">/</span><strong>{section}</strong></div><div className="flex items-center gap-4"><span className="project-tag">TARP PROJECT</span><span className="hidden text-xs text-slate-500 sm:inline">Human review, supported by evidence</span></div></header><main className="app-content"><Outlet /></main></div>
  </div>;
}
