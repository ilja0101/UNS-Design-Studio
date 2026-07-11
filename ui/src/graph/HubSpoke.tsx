import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  useReactFlow,
  type Node,
  type Edge,
} from "@xyflow/react";
import { useGraph } from "./useGraph";
import { computeLayout } from "./layout";
import { UnsNode } from "./UnsNode";
import { NodePanel } from "./NodePanel";
import { Toolbar } from "./Toolbar";
import { mergeAssetIntoConfig } from "./unsConfig";
import { api } from "../api";
import type { AssetTemplate, GraphNode, NodeType } from "../types/graph";

const SIZE: Record<NodeType, number> = {
  enterprise: 92,
  businessUnit: 76,
  site: 66,
  area: 56,
  workCenter: 48,
  workUnit: 44,
  system: 62,
};

const nodeTypes = { uns: UnsNode };

function Canvas() {
  const g = useGraph();
  const rf = useReactFlow();
  const graph = g.graph;

  const layout = useMemo(
    () => (graph ? computeLayout(graph, g.expanded) : null),
    [graph, g.expanded],
  );

  const rfNodes: Node[] = useMemo(() => {
    if (!layout) return [];
    return layout.placed.map((p) => {
      const isCore = p.node.id === layout.rootId;
      const size = isCore ? 96 : SIZE[p.node.type] ?? 48;
      return {
        id: p.node.id,
        type: "uns",
        position: { x: p.x - size / 2, y: p.y - size / 2 },
        data: {
          node: p.node,
          isCore,
          size,
          hasChildren: g.hasChildren(p.node.id),
          expanded: g.expanded.has(p.node.id),
        },
        selected: p.node.id === g.selectedId,
        draggable: false,
      };
    });
  }, [layout, g.expanded, g.selectedId, g.hasChildren]);

  const rfEdges: Edge[] = useMemo(() => {
    if (!layout) return [];
    return layout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "straight",
      className: e.pulse ? "uns-pulse" : undefined,
      style: e.pulse ? undefined : { stroke: "var(--border)" },
    }));
  }, [layout]);

  // Fit by computing the transform directly from our own layout coords — RF's
  // fitView depends on internal node measurement timing and no-ops for custom
  // nodes here. We know every node's centre + visual size, so this is exact.
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const fit = useCallback(
    (duration = 300) => {
      const el = wrapRef.current;
      if (!el || !layout || !layout.placed.length) return;
      const w = el.clientWidth;
      const h = el.clientHeight;
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const p of layout.placed) {
        const half = (p.node.id === layout.rootId ? 96 : SIZE[p.node.type] ?? 48) / 2 + 34;
        minX = Math.min(minX, p.x - half);
        maxX = Math.max(maxX, p.x + half);
        minY = Math.min(minY, p.y - half);
        maxY = Math.max(maxY, p.y + half);
      }
      const bw = maxX - minX || 1;
      const bh = maxY - minY || 1;
      const zoom = Math.max(0.2, Math.min(1.4, w / (bw * 1.14), h / (bh * 1.14)));
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      rf.setViewport({ x: w / 2 - cx * zoom, y: h / 2 - cy * zoom, zoom }, { duration });
    },
    [layout, rf],
  );

  // Refit on any topology change. React Flow can override the viewport during
  // its own early mount/measure phase, so on the first paint we retry across a
  // short window until one lands after it settles; later changes just fit once.
  const sig = useMemo(() => rfNodes.map((n) => n.id).join(","), [rfNodes]);
  const firstFit = useRef(true);
  useEffect(() => {
    if (!sig) return;
    const delays = firstFit.current ? [80, 320, 700, 1300] : [60];
    firstFit.current = false;
    const timers = delays.map((d, i) => setTimeout(() => fit(i === 0 ? 0 : 260), d));
    return () => timers.forEach(clearTimeout);
  }, [sig, fit]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => fit(0));
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  const onAddAsset = async (path: string, asset: AssetTemplate) => {
    const cfg = await api.uns();
    g.saveUns.mutate(mergeAssetIntoConfig(cfg, path, asset));
  };

  const busy = g.setLive.isPending || g.resetLive.isPending || g.saveUns.isPending;

  return (
    <div ref={wrapRef} className="relative h-full w-full">
      <Toolbar
        graph={graph}
        onAllLive={() => g.resetLive.mutate("all")}
        onClear={() => g.resetLive.mutate("none")}
        busy={busy}
      />
      {g.selected && (
        <NodePanel
          node={g.selected}
          allNodes={graph?.nodes ?? []}
          onSetLive={(p, live) => g.setLive.mutate({ path: p, live })}
          onAddAsset={onAddAsset}
          onClose={() => g.setSelectedId(null)}
          busy={busy}
        />
      )}
      {graph && graph.nodes.length === 0 && (
        <div className="absolute inset-0 grid place-items-center text-center text-fg-muted">
          <div>
            <p className="text-sm font-medium">No UNS modelled yet.</p>
            <p className="mt-1 text-xs">
              Open the <a className="text-accent underline" href="/uns">UNS Designer</a> to build one.
            </p>
          </div>
        </div>
      )}
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onInit={() => fit(0)}
        minZoom={0.2}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => {
          const gn = n.data.node as GraphNode;
          if (n.id === layout?.rootId) {
            g.collapseAll();
            g.setSelectedId(null);
            return;
          }
          g.setSelectedId(gn.id);
          if (g.hasChildren(gn.id)) g.toggleExpand(gn.id);
        }}
        onPaneClick={() => g.setSelectedId(null)}
      >
        <Background gap={22} color="var(--surface-3)" />
      </ReactFlow>
    </div>
  );
}

export function HubSpoke() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  );
}
