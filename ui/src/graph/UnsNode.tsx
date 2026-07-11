import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Network,
  Building2,
  Factory,
  LayoutGrid,
  Cog,
  Box,
  Server,
  ChevronRight,
} from "lucide-react";
import type { GraphNode, NodeType } from "../types/graph";

export interface UnsNodeData {
  node: GraphNode;
  isCore: boolean;
  size: number;
  hasChildren: boolean;
  expanded: boolean;
  [key: string]: unknown;
}

const ICON: Record<NodeType, typeof Network> = {
  enterprise: Network,
  businessUnit: Building2,
  site: Factory,
  area: LayoutGrid,
  workCenter: Cog,
  workUnit: Box,
  system: Server,
};

export const UnsNode = memo(function UnsNode({ data, selected }: NodeProps) {
  const d = data as unknown as UnsNodeData;
  const { node, isCore, size, hasChildren, expanded } = d;
  const Icon = ICON[node.type] ?? Box;

  // State palette: live+running = ok, live+stopped = warn, offline = muted.
  const state = !node.live ? "off" : node.running ? "on" : "idle";
  const ring =
    isCore
      ? "border-accent bg-accent text-accent-fg"
      : state === "on"
        ? "border-ok bg-ok-soft text-fg"
        : state === "idle"
          ? "border-warn bg-warn-soft text-fg"
          : "border-border bg-surface text-fg-muted";
  const square = node.type === "system";

  return (
    <div className="group flex flex-col items-center" style={{ width: size }}>
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div
        title={node.description || node.name}
        className={`grid place-items-center border-2 transition-tokens ${ring} ${
          square ? "rounded-xl" : "rounded-full"
        } ${selected ? "ring-2 ring-accent ring-offset-2 ring-offset-bg" : ""} ${
          node.live && node.running ? "shadow-[0_0_0_4px_var(--state-ok-soft)]" : ""
        }`}
        style={{ width: size, height: size }}
      >
        <Icon size={Math.round(size * 0.34)} />
        {hasChildren && !isCore && (
          <span
            className={`absolute -bottom-1 grid h-4 w-4 place-items-center rounded-full border border-border bg-surface text-fg-muted transition-transform ${
              expanded ? "rotate-90" : ""
            }`}
          >
            <ChevronRight size={11} />
          </span>
        )}
      </div>
      <div
        className={`pointer-events-none mt-1 max-w-[120px] truncate text-center text-[11px] font-medium ${
          isCore ? "text-fg" : "text-fg-muted"
        }`}
      >
        {node.name}
      </div>
      {node.tagCount > 0 && (
        <div className="pointer-events-none text-[9px] text-fg-faint">{node.tagCount} tags</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
});
