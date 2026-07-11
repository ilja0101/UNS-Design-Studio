import { Radio, Trash2, Sparkles, Loader2 } from "lucide-react";
import type { GraphResponse } from "../types/graph";

export function Toolbar({
  graph,
  onAllLive,
  onClear,
  busy,
}: {
  graph: GraphResponse | undefined;
  onAllLive: () => void;
  onClear: () => void;
  busy: boolean;
}) {
  const liveMode = graph?.liveMode ?? "all";
  const rate = graph?.bridge.msgsPerSec ?? 0;
  const connected = graph?.bridge.connected;
  return (
    <div className="absolute left-4 top-4 z-10 flex items-center gap-2 rounded-xl border border-border bg-surface/90 px-2.5 py-1.5 shadow-card backdrop-blur">
      <span className="flex items-center gap-1.5 text-[12px] text-fg-muted">
        <Radio size={14} className={connected ? "text-ok" : "text-fg-faint"} />
        {connected ? `${graph?.bridge.protocol} · ${rate.toFixed(0)} msg/s` : "bridge offline"}
      </span>
      <span className="h-4 w-px bg-border" />
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
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />} Clear live UNS
      </button>
    </div>
  );
}
