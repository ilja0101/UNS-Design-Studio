import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  Network,
  PencilRuler,
  FileJson,
  Radio,
  LayoutDashboard,
  Settings,
  BookOpen,
} from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { ShiftBadge } from "./ShiftBadge";

// Internal SPA routes vs. legacy Jinja pages (linked out during migration).
const internal = [{ to: "/", label: "UNS Hub", icon: Network }];
const legacy = [
  { href: "/uns", label: "UNS Designer", icon: PencilRuler },
  { href: "/payload-schemas", label: "Payload Schemas", icon: FileJson },
  { href: "/live", label: "Live UNS View", icon: Radio },
  { href: "/viz", label: "Visualization", icon: LayoutDashboard },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/manual", label: "User Manual", icon: BookOpen },
];

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-56 shrink-0 flex-col bg-sidebar text-sidebar-fg">
        <div className="flex items-center gap-2 px-4 py-4">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-accent-fg">
            <Network size={18} />
          </span>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white">UNS Design Studio</div>
            <div className="text-[10px] uppercase tracking-wider opacity-60">Simulator Node</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-2">
          <p className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider opacity-50">
            Overview
          </p>
          {internal.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm ${
                  isActive ? "bg-sidebar-active text-white" : "hover:bg-sidebar-active/60"
                }`
              }
            >
              <Icon size={16} /> {label}
            </NavLink>
          ))}
          <p className="px-2 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider opacity-50">
            Design &amp; Operations
          </p>
          {legacy.map(({ href, label, icon: Icon }) => (
            <a
              key={href}
              href={href}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm hover:bg-sidebar-active/60"
            >
              <Icon size={16} /> {label}
            </a>
          ))}
        </nav>
        <div className="px-4 py-3 text-[10px] opacity-40">v2.0 · Hub-spoke</div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-surface px-4 py-2.5">
          <h1 className="text-sm font-semibold text-fg">Unified Namespace</h1>
          <span className="text-xs text-fg-muted">live topology</span>
          <div className="ml-auto flex items-center gap-2">
            <ShiftBadge />
            <ThemeToggle />
          </div>
        </header>
        <main className="min-h-0 flex-1 bg-bg">{children}</main>
      </div>
    </div>
  );
}
