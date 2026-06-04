import { NavLink, Outlet } from "react-router-dom";
import {
  CircleDot,
  GitPullRequestArrow,
  LayoutDashboard,
  ListTree,
  Radio,
  ShieldCheck,
  FlaskConical,
  ScanSearch,
  Scale,
  Sparkles,
  Settings as SettingsIcon,
  Moon,
  Sun,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useTheme";
import { StatusBar } from "./StatusBar";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}
interface NavSection {
  heading: string;
  items: NavItem[];
}

// Grouped to mirror the optimization loop: observe → evaluate → improve.
const SECTIONS: NavSection[] = [
  {
    heading: "Monitor",
    items: [
      { to: "/overview", label: "Overview", icon: LayoutDashboard },
      { to: "/traces", label: "Traces", icon: ListTree },
      { to: "/mcp-log", label: "Agent ↔ Kyoko", icon: Radio },
    ],
  },
  {
    heading: "Evaluate",
    items: [
      { to: "/detectors", label: "Detectors", icon: ScanSearch },
      { to: "/judges", label: "Judges", icon: Scale },
      { to: "/checks", label: "Checks & Replay", icon: FlaskConical },
    ],
  },
  {
    heading: "Improve",
    items: [
      { to: "/issues", label: "Review", icon: CircleDot },
      { to: "/analysis", label: "Analysis", icon: Sparkles },
      { to: "/proposals", label: "Proposals", icon: GitPullRequestArrow },
      { to: "/autonomy", label: "Autonomy", icon: ShieldCheck },
    ],
  },
];

function NavRow({ to, label, icon: Icon }: NavItem) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-2.5 rounded-lg border-l-[3px] px-2.5 py-2 text-sm font-medium transition-colors",
          isActive
            ? "border-primary bg-accent text-foreground shadow-sm"
            : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground",
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon className={cn("h-4 w-4 shrink-0", isActive ? "text-primary" : "text-muted-foreground")} />
          {label}
        </>
      )}
    </NavLink>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      className="group flex items-center gap-2.5 rounded-lg border-l-[3px] border-transparent px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? <Sun className="h-4 w-4 shrink-0" /> : <Moon className="h-4 w-4 shrink-0" />}
      {isDark ? "Light mode" : "Dark mode"}
    </button>
  );
}

export function Layout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
        <div className="flex h-14 items-center gap-2.5 px-5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-xs">
            <span className="text-sm font-bold leading-none">京</span>
          </div>
          <div className="flex flex-col leading-none">
            <span className="text-md font-bold tracking-tight">Kyoko</span>
            <span className="mt-0.5 text-xs font-medium text-muted-foreground">
              Optimization loop
            </span>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-3">
          {SECTIONS.map((section) => (
            <div key={section.heading} className="flex flex-col gap-1">
              <div className="px-2.5 pb-1 text-xs font-medium text-muted-foreground">
                {section.heading}
              </div>
              {section.items.map((item) => (
                <NavRow key={item.to} {...item} />
              ))}
            </div>
          ))}
          <div className="mt-auto flex flex-col gap-1 border-t border-sidebar-border pt-3">
            <NavRow to="/settings" label="Settings" icon={SettingsIcon} />
            <ThemeToggle />
          </div>
        </nav>
        <StatusBar />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
