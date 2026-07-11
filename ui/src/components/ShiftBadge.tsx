import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

const LOOK: Record<string, { emoji: string; label: string; cls: string }> = {
  open: { emoji: "🟢", label: "On shift", cls: "text-ok" },
  closed: { emoji: "🌙", label: "Off shift", cls: "text-fg-muted" },
  dayoff: { emoji: "🎣", label: "Day off", cls: "text-accent" },
};

function countdown(iso?: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (isNaN(ms) || ms <= 0) return "any moment";
  const m = Math.round(ms / 60000);
  const h = Math.floor(m / 60);
  if (h >= 24) return `in ${Math.floor(h / 24)}d ${h % 24}h`;
  return `in ${h ? h + "h " : ""}${m % 60}m`;
}

/** Ported from the legacy dashboard header badge — polls /api/shift. */
export function ShiftBadge() {
  const { data } = useQuery({
    queryKey: ["shift"],
    queryFn: api.shift,
    refetchInterval: 15000,
  });
  if (!data || !data.enabled) return null;
  const look = LOOK[data.state] ?? LOOK.closed;
  const when = countdown(data.next_change);
  const verb = data.state === "open" ? "clocks out" : "clocks in";
  return (
    <a
      href="/settings"
      title="Production shift schedule — configure in Settings"
      className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1 text-[12px] text-fg no-underline hover:border-accent"
    >
      <span className={`font-semibold ${look.cls}`}>
        {look.emoji} {look.label}
      </span>
      <span className="text-fg-muted">
        {data.running}/{data.total}
        {when ? ` · ${verb} ${when}` : ""}
      </span>
    </a>
  );
}
