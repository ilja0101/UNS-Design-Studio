import { describe, it, expect } from "vitest";
import { computeLayout, rootIdOf } from "./layout";
import type { GraphNode, GraphResponse } from "../types/graph";

function n(id: string, type: GraphNode["type"], parentId: string | null, extra: Partial<GraphNode> = {}): GraphNode {
  return {
    id, type, parentId, name: id.split("|").pop()!, depth: id.split("|").length - 1,
    live: true, running: true, hasTags: false, tagCount: 0, plantKey: null, publishRate: 0, ...extra,
  };
}

function graph(nodes: GraphNode[], singleBU: boolean): GraphResponse {
  return {
    enterprise: { id: "E", name: "E" }, singleBusinessUnit: singleBU, nodes,
    liveMode: "all", simulatorRunning: true, server: { running: true },
    bridge: { connected: true, running: true, protocol: "nats", msgsPerSec: 1, perPlant: {} },
  };
}

const SINGLE = [
  n("E", "enterprise", null),
  n("E|B", "businessUnit", "E"),
  n("E|B|S1", "site", "E|B"),
  n("E|B|S1|A1", "area", "E|B|S1"),
  n("E|B|S2", "site", "E|B"),
];
const MULTI = [
  n("E", "enterprise", null),
  n("E|B1", "businessUnit", "E"),
  n("E|B1|S1", "site", "E|B1"),
  n("E|B2", "businessUnit", "E"),
];

describe("rootIdOf", () => {
  it("single BU → the BU is the core", () => {
    expect(rootIdOf(graph(SINGLE, true))).toBe("E|B");
  });
  it("multi BU → the enterprise is the core", () => {
    expect(rootIdOf(graph(MULTI, false))).toBe("E");
  });
});

describe("computeLayout", () => {
  it("collapsed single-BU shows core + ring-1 sites only", () => {
    const l = computeLayout(graph(SINGLE, true), new Set());
    const ids = l.placed.map((p) => p.node.id).sort();
    expect(ids).toEqual(["E|B", "E|B|S1", "E|B|S2"]); // area hidden until S1 expands
    expect(l.placed.find((p) => p.node.id === "E|B")!.ring).toBe(0);
    expect(l.placed.find((p) => p.node.id === "E|B|S1")!.ring).toBe(1);
  });

  it("expanding a site reveals its area on the next ring", () => {
    const l = computeLayout(graph(SINGLE, true), new Set(["E|B|S1"]));
    const a1 = l.placed.find((p) => p.node.id === "E|B|S1|A1");
    expect(a1).toBeTruthy();
    expect(a1!.ring).toBe(2);
  });

  it("core sits at the origin; ring-1 nodes are off-origin", () => {
    const l = computeLayout(graph(SINGLE, true), new Set());
    const core = l.placed.find((p) => p.node.id === "E|B")!;
    expect(Math.hypot(core.x, core.y)).toBeCloseTo(0);
    const s1 = l.placed.find((p) => p.node.id === "E|B|S1")!;
    expect(Math.hypot(s1.x, s1.y)).toBeGreaterThan(100);
  });

  it("multi-BU renders BUs around the enterprise core", () => {
    const l = computeLayout(graph(MULTI, false), new Set());
    const ids = l.placed.map((p) => p.node.id).sort();
    expect(ids).toEqual(["E", "E|B1", "E|B2"]); // BU1's site hidden until expanded
  });

  it("edges connect visible parents and pulse only when live+running", () => {
    const nodes = SINGLE.map((x) => (x.id === "E|B|S2" ? { ...x, running: false } : x));
    const l = computeLayout(graph(nodes, true), new Set());
    const e1 = l.edges.find((e) => e.target === "E|B|S1")!;
    const e2 = l.edges.find((e) => e.target === "E|B|S2")!;
    expect(e1.pulse).toBe(true);
    expect(e2.pulse).toBe(false); // S2 not running
  });
});
