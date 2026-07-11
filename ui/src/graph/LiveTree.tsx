import { useMemo, useState } from "react";
import { ChevronRight, ListTree, PanelRightClose } from "lucide-react";
import type { GraphNode } from "../types/graph";

interface TreeNode {
  name: string;
  id: string;
  children: TreeNode[];
  hasTags: boolean;
  running: boolean;
  live: boolean; // false for a structural ancestor that isn't itself a member
}

// Fold the live (member) nodes into a topic tree. This reflects the *intended*
// live UNS (membership) — it updates instantly on add/remove without needing a
// broker. (A future mode could subscribe to the actual bus.)
//
// Every live node is attached under its real ancestor chain up to the root, so
// two sibling members (e.g. two sites under one business unit) aggregate under
// their shared parent instead of one replacing the other. Ancestors that aren't
// themselves live are drawn as faint structural nodes.
function buildTree(nodes: GraphNode[]): TreeNode | null {
  const live = nodes.filter((n) => n.live);
  if (!live.length) return null;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const map = new Map<string, TreeNode>();
  const ensure = (n: GraphNode): TreeNode => {
    let t = map.get(n.id);
    if (!t) {
      t = { name: n.name, id: n.id, children: [], hasTags: n.hasTags, running: n.running, live: n.live };
      map.set(n.id, t);
    }
    return t;
  };

  const roots = new Set<string>();
  for (const n of live) {
    ensure(n);
    // Walk up the real ancestor chain, materialising each ancestor and linking
    // child→parent. The topmost reachable ancestor becomes a root.
    let cur: GraphNode | undefined = n;
    while (cur) {
      const parent: GraphNode | undefined = cur.parentId ? byId.get(cur.parentId) : undefined;
      if (!parent) {
        roots.add(cur.id);
        break;
      }
      const pt = ensure(parent);
      const ct = ensure(cur);
      if (!pt.children.includes(ct)) pt.children.push(ct);
      cur = parent;
    }
  }

  // Single root in a well-formed enterprise tree; if several, wrap them.
  const rootIds = [...roots];
  if (rootIds.length === 1) return map.get(rootIds[0]) ?? null;
  const shallow = rootIds
    .map((id) => byId.get(id))
    .filter(Boolean)
    .sort((a, b) => (a!.depth - b!.depth))[0];
  return shallow ? map.get(shallow.id) ?? null : null;
}

function Row({ node, depth }: { node: TreeNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const has = node.children.length > 0;
  return (
    <div>
      <button
        onClick={() => has && setOpen((o) => !o)}
        className="flex w-full items-center gap-1 rounded px-1 py-[3px] text-left text-[12px] hover:bg-surface-2"
        style={{ paddingLeft: 4 + depth * 12 }}
      >
        <ChevronRight
          size={12}
          className={`shrink-0 text-fg-faint transition-transform ${has ? (open ? "rotate-90" : "") : "opacity-0"}`}
        />
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            !node.live ? "border border-fg-faint" : node.running ? "bg-ok" : "bg-fg-faint"
          }`}
        />
        <span className={`truncate font-mono ${node.live ? "text-fg" : "text-fg-muted"}`} title={node.id}>
          {node.name}
        </span>
        {node.hasTags && <span className="ml-auto shrink-0 text-[9px] text-fg-faint">tags</span>}
      </button>
      {open && node.children.map((c) => <Row key={c.id} node={c} depth={depth + 1} />)}
    </div>
  );
}

export function LiveTree({ nodes, liveCount }: { nodes: GraphNode[]; liveCount: number }) {
  const [open, setOpen] = useState(true);
  const tree = useMemo(() => buildTree(nodes), [nodes]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="Show live UNS tree"
        className="absolute right-4 top-4 z-10 grid h-9 w-9 place-items-center rounded-lg border border-border bg-surface text-fg-muted shadow-card hover:text-accent"
      >
        <ListTree size={16} />
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 right-4 top-4 z-10 flex w-64 flex-col rounded-xl border border-border bg-surface shadow-pop">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <ListTree size={15} className="text-accent" />
        <span className="text-sm font-semibold text-fg">Live UNS</span>
        <span className="rounded bg-surface-2 px-1.5 text-[10px] font-medium text-fg-muted">{liveCount}</span>
        <button onClick={() => setOpen(false)} className="ml-auto text-fg-faint hover:text-fg">
          <PanelRightClose size={15} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {tree ? (
          <Row node={tree} depth={0} />
        ) : (
          <p className="px-2 py-6 text-center text-[12px] text-fg-muted">
            Nothing live. Click a node → <span className="text-accent">Add to live UNS</span>.
          </p>
        )}
      </div>
    </div>
  );
}
