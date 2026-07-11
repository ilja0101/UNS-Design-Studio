import type { GraphNode, GraphResponse } from "../types/graph";

// Radial hub-spoke layout — pure functions of (graph, expanded), unit-tested.
// Core at the origin; ring-1 spokes around it; expanded branches fan out within
// their parent's angular sector (an "accordion": expanding widens that sector).

export interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  ring: number; // depth from the layout root (core = 0)
}
export interface LayoutEdge {
  id: string;
  source: string;
  target: string;
  pulse: boolean;
}
export interface Layout {
  rootId: string;
  placed: Placed[];
  edges: LayoutEdge[];
}

function radius(ring: number): number {
  return ring <= 0 ? 0 : 220 + (ring - 1) * 165;
}

/** The node whose children form ring 1: the single BU (collapsed core) or the enterprise. */
export function rootIdOf(graph: GraphResponse): string {
  if (graph.singleBusinessUnit) {
    const bu = graph.nodes.find((n) => n.type === "businessUnit");
    if (bu) return bu.id;
  }
  const ent = graph.nodes.find((n) => n.type === "enterprise");
  return ent ? ent.id : graph.enterprise.id;
}

export function computeLayout(graph: GraphResponse, expanded: Set<string>): Layout {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const childrenOf = new Map<string, GraphNode[]>();
  for (const n of graph.nodes) {
    if (n.parentId) {
      const arr = childrenOf.get(n.parentId) ?? [];
      arr.push(n);
      childrenOf.set(n.parentId, arr);
    }
  }
  const rootId = rootIdOf(graph);

  // Visible children in the layout: the root always shows its children (ring 1);
  // any other node shows its children only when expanded.
  const kidsOf = (id: string, isRoot: boolean): GraphNode[] =>
    isRoot || expanded.has(id) ? childrenOf.get(id) ?? [] : [];

  const weight = (id: string, isRoot: boolean): number => {
    const kids = kidsOf(id, isRoot);
    if (!kids.length) return 1;
    return kids.reduce((s, k) => s + weight(k.id, false), 0);
  };

  const placed: Placed[] = [];
  const place = (node: GraphNode, isRoot: boolean, a0: number, a1: number, ring: number) => {
    const mid = (a0 + a1) / 2;
    const r = radius(ring);
    placed.push({
      node,
      x: isRoot ? 0 : r * Math.cos(mid),
      y: isRoot ? 0 : r * Math.sin(mid),
      ring,
    });
    const kids = kidsOf(node.id, isRoot);
    if (!kids.length) return;
    const total = kids.reduce((s, k) => s + weight(k.id, false), 0);
    const gutter = Math.min(0.12, (a1 - a0) * 0.04);
    const span = a1 - a0 - gutter;
    let cursor = a0 + gutter / 2;
    for (const k of kids) {
      const w = weight(k.id, false) / total;
      const k1 = cursor + span * w;
      place(k, false, cursor, k1, ring + 1);
      cursor = k1;
    }
  };

  const root = byId.get(rootId);
  if (root) place(root, true, -Math.PI / 2, (3 * Math.PI) / 2, 0);

  const visible = new Set(placed.map((p) => p.node.id));
  const pulsing = graph.simulatorRunning && graph.bridge.connected;
  const edges: LayoutEdge[] = [];
  for (const p of placed) {
    const parent = p.node.parentId;
    if (parent && visible.has(parent)) {
      edges.push({
        id: `${parent}->${p.node.id}`,
        source: parent,
        target: p.node.id,
        pulse: pulsing && p.node.live && p.node.running,
      });
    }
  }
  return { rootId, placed, edges };
}
