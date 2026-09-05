import type { UnsNodeType, UnsTreeNode, UnsTag } from "../../api";

export interface NodeMeta {
  label: string;
  color: string;
  next: UnsNodeType;
}

// ISA-95 hierarchy metadata. Colours come from the family state palette so the
// tree reads consistently in light/dark.
export const NT: Record<UnsNodeType, NodeMeta> = {
  enterprise: { label: "Enterprise", color: "#3b82f6", next: "businessUnit" },
  businessUnit: { label: "Business Unit", color: "#8b5cf6", next: "site" },
  site: { label: "Site", color: "#16a34a", next: "area" },
  area: { label: "Area", color: "#f59e0b", next: "workCenter" },
  workCenter: { label: "Work Center", color: "#eab308", next: "workUnit" },
  workUnit: { label: "Work Unit", color: "#ef4444", next: "device" },
  device: { label: "Device", color: "#64748b", next: "folder" },
  // Organisational tag folder (e.g. cmd / setpoint) — groups tags, not a device.
  folder: { label: "Folder", color: "#94a3b8", next: "folder" },
};

export const NODE_ORDER: UnsNodeType[] = [
  "enterprise",
  "businessUnit",
  "site",
  "area",
  "workCenter",
  "workUnit",
  "device",
  "folder",
];

export const uid = () =>
  "n-" + Date.now().toString(36) + "-" + Math.random().toString(16).slice(2, 8);

export function find(root: UnsTreeNode | undefined, id: string): UnsTreeNode | null {
  if (!root) return null;
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = find(c, id);
    if (f) return f;
  }
  return null;
}

export function findParent(
  root: UnsTreeNode | undefined,
  id: string,
  parent: UnsTreeNode | null = null,
): UnsTreeNode | null | undefined {
  if (!root) return undefined;
  if (root.id === id) return parent;
  for (const c of root.children ?? []) {
    const f = findParent(c, id, root);
    if (f !== undefined) return f;
  }
  return undefined;
}

export function topicPath(root: UnsTreeNode, id: string): string {
  const parents = new Map<string, string | null>();
  const nodes = new Map<string, UnsTreeNode>();
  const walk = (n: UnsTreeNode, p: string | null) => {
    nodes.set(n.id, n);
    parents.set(n.id, p);
    (n.children ?? []).forEach((c) => walk(c, n.id));
  };
  walk(root, null);
  const parts: string[] = [];
  let cur: string | null | undefined = id;
  while (cur) {
    const n = nodes.get(cur);
    if (n) parts.unshift(n.name);
    cur = parents.get(cur);
  }
  return parts.join("/");
}

export function allTagPaths(node: UnsTreeNode, prefix = ""): string[] {
  const np = prefix ? `${prefix}/${node.name}` : node.name;
  const out: string[] = [];
  (node.tags ?? []).forEach((t) => out.push(`${np}/${t.name}`));
  (node.children ?? []).forEach((c) => out.push(...allTagPaths(c, np)));
  return out;
}

export const countNodes = (n?: UnsTreeNode): number =>
  n ? 1 + (n.children ?? []).reduce((s, c) => s + countNodes(c), 0) : 0;
export const countTags = (n?: UnsTreeNode): number =>
  n ? (n.tags ?? []).length + (n.children ?? []).reduce((s, c) => s + countTags(c), 0) : 0;
export const maxDepth = (n?: UnsTreeNode, d = 0): number =>
  !n || !(n.children ?? []).length ? d : Math.max(...n.children!.map((c) => maxDepth(c, d + 1)));

/** Tags carrying an answer key (`_truth`) anywhere in the subtree. */
export const countTruth = (n?: UnsTreeNode): number =>
  n
    ? (n.tags ?? []).filter((t) => t._truth).length +
      (n.children ?? []).reduce((s, c) => s + countTruth(c), 0)
    : 0;

export function subtreeMatch(n: UnsTreeNode, q: string): boolean {
  if (!q) return true;
  const lq = q.toLowerCase();
  if (n.name.toLowerCase().includes(lq) || (n.description ?? "").toLowerCase().includes(lq)) return true;
  if ((n.tags ?? []).some((t) => t.name.toLowerCase().includes(lq))) return true;
  return (n.children ?? []).some((c) => subtreeMatch(c, q));
}

export function newTag(): UnsTag {
  return {
    id: uid(),
    name: "NewTag",
    dataType: "Float",
    unit: "",
    description: "",
    access: "R",
    payloadSchema: "",
    simulation: null,
  };
}

export function newNode(type: UnsNodeType): UnsTreeNode {
  return {
    id: uid(),
    name: `New${NT[type].label.replace(/\s/g, "")}`,
    type,
    description: "",
    tags: [],
    children: [],
  };
}

// Deep-clone a subtree and re-key every node + tag id (for duplication).
export function reId(n: UnsTreeNode): UnsTreeNode {
  const copy: UnsTreeNode = structuredClone(n);
  const walk = (node: UnsTreeNode) => {
    node.id = uid();
    (node.tags ?? []).forEach((t) => (t.id = uid()));
    (node.children ?? []).forEach(walk);
  };
  walk(copy);
  return copy;
}

/** plant_key = "BusinessUnit|siteName" — matches sim_state.json (site nodes only). */
export function plantKey(root: UnsTreeNode, node: UnsTreeNode): string | null {
  if (node.type !== "site") return null;
  const parent = findParent(root, node.id);
  return parent ? `${parent.name}|${node.name}` : null;
}
