import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  CircleDot,
  GitPullRequestArrow,
  LayoutDashboard,
  ListTree,
  Radio,
  ShieldCheck,
  FlaskConical,
  Settings as SettingsIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { StatusBar } from "./StatusBar";

const NAV = [
  { to: "/overview", label: "Overview", icon: LayoutDashboard },
  { to: "/runs", label: "Runs", icon: ListTree },
  { to: "/mcp-log", label: "Agent ↔ Kyoko", icon: Radio },
  { to: "/proposals", label: "Proposals", icon: GitPullRequestArrow },
  { to: "/issues", label: "Issues", icon: CircleDot },
  { to: "/autonomy", label: "Autonomy", icon: ShieldCheck },
  { to: "/evals", label: "Evals & Replay", icon: FlaskConical },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Layout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <aside className="flex w-52 shrink-0 flex-col border-r border-white/[0.06] bg-card/40">
        <div className="flex h-12 items-center gap-2 px-4">
          <Activity className="h-4 w-4 text-primary" />
          <span className="text-md font-semibold tracking-tight">Kyoko</span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 px-2 py-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  isActive
                    ? "bg-white/[0.08] text-foreground"
                    : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <StatusBar />
      </aside>
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
