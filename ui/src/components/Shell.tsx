import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  Network,
  PencilRuler,
  FileJson,
  Radio,
  LayoutDashboard,
  Settings,
  BookOpen,
  Info,
  Github,
  User,
  Tag,
  Sparkles,
} from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { ShiftBadge } from "./ShiftBadge";

const APP_INFO = {
  name: "UNS Design Studio",
  version: "2.0.0",
  author: "Ilja Bartels",
  repo: "github.com/ilja0101/UNS-Design-Studio",
  repoUrl: "https://github.com/ilja0101/UNS-Design-Studio",
};

function InfoButton() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="rise-in absolute bottom-9 left-2 z-20 w-56 rounded-xl border border-border bg-surface p-3 text-fg shadow-pop">
            <div className="mb-2 flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-accent-fg">
                <Network size={15} />
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{APP_INFO.name}</div>
                <div className="text-[10px] text-fg-muted">UNS simulator node</div>
              </div>
            </div>
            <dl className="flex flex-col gap-1.5 text-[11px]">
              <div className="flex items-center gap-2">
                <Tag size={12} className="shrink-0 text-fg-faint" />
                <span className="text-fg-muted">Version</span>
                <span className="ml-auto font-mono text-fg">{APP_INFO.version}</span>
              </div>
              <div className="flex items-center gap-2">
                <User size={12} className="shrink-0 text-fg-faint" />
                <span className="text-fg-muted">Author</span>
                <span className="ml-auto truncate text-fg">{APP_INFO.author}</span>
              </div>
              <a
                href={APP_INFO.repoUrl}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 hover:text-accent"
              >
                <Github size={12} className="shrink-0 text-fg-faint" />
                <span className="text-fg-muted">Repo</span>
                <span className="ml-auto truncate text-accent underline">source</span>
              </a>
            </dl>
          </div>
        </>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-[11px] opacity-70 hover:bg-sidebar-active/60 hover:opacity-100"
      >
        <Info size={14} />
        <span>About</span>
        <span className="ml-auto font-mono opacity-70">v{APP_INFO.version}</span>
      </button>
    </div>
  );
}

// Internal SPA routes vs. legacy Jinja pages (linked out during migration).
const internal = [
  { to: "/start", label: "Quick start", icon: Sparkles },
  { to: "/", label: "UNS Hub", icon: Network },
  { to: "/settings", label: "Settings", icon: Settings },
];
// Every page is now a native SPA route.
const design = [
  { to: "/uns", label: "UNS Designer", icon: PencilRuler },
  { to: "/payload-schemas", label: "Payload Schemas", icon: FileJson },
  { to: "/live", label: "Live UNS View", icon: Radio },
  { to: "/viz", label: "Visualization", icon: LayoutDashboard },
  { to: "/manual", label: "User Manual", icon: BookOpen },
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
              end={to === "/"}
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
          {design.map(({ to, label, icon: Icon }) => (
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
        </nav>
        <div className="px-2 py-2">
          <InfoButton />
        </div>
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
