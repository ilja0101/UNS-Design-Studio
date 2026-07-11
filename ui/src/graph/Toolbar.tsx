import { Radio, Trash2, Sparkles, Loader2, Power, Cable, Play, Pause } from "lucide-react";
import type { GraphResponse } from "../types/graph";

// The master "main switch": one control that runs / pauses the whole simulation
// (sets simulator_running + all plants). Shift-hours toggles this same flag on a
// schedule, so this reflects and overrides the current shift state.
function MainSwitch({
  on,
  onToggle,
  busy,
}: {
  on: boolean;
  onToggle: (next: boolean) => void;
  busy: boolean;
}) {
  return (
    <button
      onClick={() => onToggle(!on)}
      disabled={busy}
      title={on ? "Pause the simulation (stop all plants)" : "Run the simulation (start all plants)"}
      className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-semibold shadow-card transition-tokens disabled:opacity-50 ${
        on
          ? "border-ok/50 bg-ok text-white"
          : "border-border bg-surface text-fg-muted hover:border-accent hover:text-accent"
      }`}
    >
      {busy ? (
        <Loader2 size={15} className="animate-spin" />
      ) : on ? (
        <Pause size={15} />
      ) : (
        <Play size={15} />
      )}
      <span>{on ? "Simulation running" : "Simulation paused"}</span>
    </button>
  );
}

function Pill({
  on,
  label,
  onToggle,
  busy,
  Icon,
  detail,
}: {
  on: boolean;
  label: string;
  onToggle: (next: boolean) => void;
  busy: boolean;
  Icon: typeof Power;
  detail?: string;
}) {
  return (
    <button
      onClick={() => onToggle(!on)}
      disabled={busy}
      title={`${on ? "Stop" : "Start"} ${label}`}
      className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[12px] transition-tokens disabled:opacity-50 ${
        on
          ? "border-ok/40 bg-ok-soft text-ok"
          : "border-border bg-surface text-fg-muted hover:border-accent hover:text-accent"
      }`}
    >
      {busy ? <Loader2 size={13} className="animate-spin" /> : <Icon size={13} />}
      <span className="font-medium">{label}</span>
      <span className={`h-1.5 w-1.5 rounded-full ${on ? "bg-ok" : "bg-fg-faint"}`} />
      {detail && <span className="text-fg-muted">{detail}</span>}
    </button>
  );
}

export function Toolbar({
  graph,
  onSimulation,
  onAllLive,
  onClear,
  onServer,
  onBridge,
  busy,
}: {
  graph: GraphResponse | undefined;
  onSimulation: (on: boolean) => void;
  onAllLive: () => void;
  onClear: () => void;
  onServer: (on: boolean) => void;
  onBridge: (on: boolean) => void;
  busy: boolean;
}) {
  const liveMode = graph?.liveMode ?? "all";
  const simOn = graph?.simulatorRunning ?? false;
  const serverOn = graph?.server?.running ?? false;
  const bridgeOn = graph?.bridge.running ?? false;
  const rate = graph?.bridge.msgsPerSec ?? 0;
  return (
    <div className="absolute left-4 top-4 z-10 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface/90 px-2.5 py-1.5 shadow-card backdrop-blur">
      <MainSwitch on={simOn} onToggle={onSimulation} busy={busy} />
      <span className="h-4 w-px bg-border" />
      <Pill on={serverOn} label="OPC-UA" onToggle={onServer} busy={busy} Icon={Power} />
      <Pill
        on={bridgeOn}
        label="Bridge"
        onToggle={onBridge}
        busy={busy}
        Icon={Cable}
        detail={bridgeOn ? `${graph?.bridge.protocol} · ${rate.toFixed(0)}/s` : undefined}
      />
      <span className="h-4 w-px bg-border" />
      <span className="flex items-center gap-1.5 text-[11px] text-fg-faint">
        <Radio size={12} className={graph?.bridge.connected ? "text-ok" : ""} />
      </span>
      <button
        onClick={onAllLive}
        disabled={busy || liveMode === "all"}
        className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-40"
      >
        <Sparkles size={13} /> All live
      </button>
      <button
        onClick={onClear}
        disabled={busy}
        className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] text-fg-muted hover:bg-err-soft hover:text-err disabled:opacity-40"
        title="Clear the live UNS — nothing publishes until you add nodes"
      >
        <Trash2 size={13} /> Clear live UNS
      </button>
    </div>
  );
}
