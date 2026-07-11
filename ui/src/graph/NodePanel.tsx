import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Plus, Zap, ZapOff, PackagePlus } from "lucide-react";
import { api } from "../api";
import type { GraphNode, AssetTemplate } from "../types/graph";

export function NodePanel({
  node,
  allNodes,
  onSetLive,
  onAddAsset,
  onClose,
  busy,
}: {
  node: GraphNode;
  allNodes: GraphNode[];
  onSetLive: (path: string, live: boolean) => void;
  onAddAsset: (path: string, asset: AssetTemplate) => void;
  onClose: () => void;
  busy: boolean;
}) {
  const [showAssets, setShowAssets] = useState(false);
  const { data: assets } = useQuery({
    queryKey: ["asset-library"],
    queryFn: api.assetLibrary,
    enabled: showAssets,
  });

  const descendants = allNodes.filter((n) => n.id.startsWith(node.id + "|")).length;
  const path = node.id.split("|");

  return (
    <div className="rise-in absolute right-4 top-4 z-10 w-72 rounded-xl border border-border bg-surface shadow-pop">
      <div className="flex items-start gap-2 border-b border-border px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-fg">{node.name}</div>
          <div className="truncate font-mono text-[10px] text-fg-faint" title={node.id}>
            {path.join(" › ")}
          </div>
        </div>
        <button onClick={onClose} className="text-fg-faint hover:text-fg">
          <X size={15} />
        </button>
      </div>

      <div className="space-y-2 px-3 py-3">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="rounded bg-surface-2 px-1.5 py-0.5 font-medium text-fg-muted">{node.type}</span>
          <span className={node.live ? "text-ok" : "text-fg-faint"}>
            {node.live ? (node.running ? "● live · publishing" : "● live · idle") : "○ not in live UNS"}
          </span>
        </div>

        {node.live ? (
          <button
            disabled={busy}
            onClick={() => onSetLive(node.id, false)}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg-muted hover:border-err hover:text-err disabled:opacity-50"
          >
            <ZapOff size={15} /> Remove from live UNS
          </button>
        ) : (
          <button
            disabled={busy}
            onClick={() => onSetLive(node.id, true)}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover disabled:opacity-50"
          >
            <Zap size={15} /> Add to live UNS
            {descendants > 0 ? ` (incl. ${descendants})` : ""}
          </button>
        )}

        <button
          onClick={() => setShowAssets((s) => !s)}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg-muted hover:border-accent hover:text-accent"
        >
          <PackagePlus size={15} /> Add asset from library
        </button>

        {showAssets && (
          <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-border bg-bg p-1.5">
            {!assets ? (
              <p className="px-1 py-2 text-[11px] text-fg-muted">Loading…</p>
            ) : (
              assets.map((a) => (
                <button
                  key={a.id}
                  disabled={busy}
                  onClick={() => onAddAsset(node.id, a)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] text-fg hover:bg-surface-2 disabled:opacity-50"
                  title={a.description}
                >
                  <Plus size={12} className="text-accent" />
                  <span className="flex-1 truncate">{a.label}</span>
                  <span className="text-[9px] text-fg-faint">{a.tags?.length ?? 0} tags</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
