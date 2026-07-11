import type { GraphNode, GraphResponse } from "../types/graph";

// Radial hub-spoke layout — pure functions of (graph, expanded), unit-tested.
//
// Positions are STRUCTURAL and stable: every node's angle/radius is derived from
// the tree shape alone (sector share ∝ subtree size), independent of what's
// expanded. Expanding a branch therefore never moves existing nodes — it only
// reveals children already parked in their parent's fixed sector, growing
// outward in that spoke's direction. The core stays pinned at the origin.

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
  maxExtent: number; // furthest visible node distance from origin (for fitting)
}

function radius(ring: number): number {
  return ring <= 0 ? 0 : 240 + (ring - 1) * 190;
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

  // Structural weight = number of leaf descendants (min 1). Stable — does not
  // depend on expansion — so sectors never resize when a branch opens.
  const weightMemo = new Map<string, number>();
  const weight = (id: string): number => {
    const cached = weightMemo.get(id);
    if (cached !== undefined) return cached;
    const kids = childrenOf.get(id) ?? [];
    const w = kids.length ? kids.reduce((s, k) => s + weight(k.id), 0) : 1;
    weightMemo.set(id, w);
    return w;
  };

  // Precompute an (angle, ring) for every node by dividing each node's angular
  // sector among its children by structural weight.
  const angleOf = new Map<string, number>();
  const ringOf = new Map<string, number>();
  const assign = (id: string, a0: number, a1: number, ring: number) => {
    angleOf.set(id, (a0 + a1) / 2);
    ringOf.set(id, ring);
    const kids = childrenOf.get(id) ?? [];
    if (!kids.length) return;
    // Children fan across a slightly narrowed slice of the parent's sector,
    // centred on the parent — keeps a branch pointing "outward".
    const total = kids.reduce((s, k) => s + weight(k.id), 0);
    const full = a1 - a0;
    const span = ring === 0 ? full : full * 0.86;
    let cursor = (a0 + a1) / 2 - span / 2;
    for (const k of kids) {
      const w = (weight(k.id) / total) * span;
      assign(k.id, cursor, cursor + w, ring + 1);
      cursor += w;
    }
  };
  const root = byId.get(rootId);
  // Start ring 1 at the top and go clockwise.
  if (root) assign(rootId, -Math.PI / 2, (3 * Math.PI) / 2, 0);

  // Visibility: the root always shows its children; deeper nodes only when the
  // parent is expanded.
  const visible = new Set<string>();
  const walkVisible = (id: string, isRoot: boolean) => {
    visible.add(id);
    if (!isRoot && !expanded.has(id)) return;
    for (const k of childrenOf.get(id) ?? []) walkVisible(k.id, false);
  };
  if (root) walkVisible(rootId, true);

  const placed: Placed[] = [];
  let maxExtent = radius(1);
  for (const n of graph.nodes) {
    if (!visible.has(n.id)) continue;
    const ring = ringOf.get(n.id) ?? 0;
    const ang = angleOf.get(n.id) ?? 0;
    const r = radius(ring);
    placed.push({ node: n, x: r * Math.cos(ang), y: r * Math.sin(ang), ring });
    maxExtent = Math.max(maxExtent, r);
  }

  const pulsing = graph.simulatorRunning && graph.bridge.connected;

  // A branch "carries flow" if it, or anything in its subtree, is live &
  // publishing. This makes data visibly stream from any live leaf all the way
  // inward: every ancestor edge on the path to the core pulses, not just the
  // leaf's own edge — even when the intermediate nodes are collapsed.
  const carries = new Map<string, boolean>();
  const carriesFlow = (id: string): boolean => {
    const cached = carries.get(id);
    if (cached !== undefined) return cached;
    const n = byId.get(id);
    let v = !!(n && n.live && n.running);
    for (const c of childrenOf.get(id) ?? []) if (carriesFlow(c.id)) v = true;
    carries.set(id, v);
    return v;
  };

  const edges: LayoutEdge[] = [];
  for (const p of placed) {
    const parent = p.node.parentId;
    if (parent && visible.has(parent)) {
      edges.push({
        id: `${parent}->${p.node.id}`,
        source: parent,
        target: p.node.id,
        pulse: pulsing && carriesFlow(p.node.id),
      });
    }
  }
  return { rootId, placed, edges, maxExtent };
}
