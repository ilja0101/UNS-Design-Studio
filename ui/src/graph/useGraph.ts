import { useCallback, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { GraphNode } from "../types/graph";

export function useGraph() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["graph"], queryFn: api.graph, refetchInterval: 2000 });

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const nodes = query.data?.nodes ?? [];
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const childrenOf = useMemo(() => {
    const m = new Map<string, GraphNode[]>();
    for (const n of nodes) if (n.parentId) (m.get(n.parentId) ?? m.set(n.parentId, []).get(n.parentId)!).push(n);
    return m;
  }, [nodes]);

  const hasChildren = useCallback((id: string) => (childrenOf.get(id)?.length ?? 0) > 0, [childrenOf]);

  // Independent expand/collapse — toggling one node never touches its siblings,
  // so you can open several branches at once and click through them freely.
  // Collapsing a node also collapses everything beneath it, so re-opening it
  // shows just the next level again.
  const toggleExpand = useCallback(
    (id: string) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
          const stack = [id];
          while (stack.length) {
            const cur = stack.pop()!;
            for (const c of childrenOf.get(cur) ?? []) {
              next.delete(c.id);
              stack.push(c.id);
            }
          }
        } else {
          next.add(id);
        }
        return next;
      });
    },
    [childrenOf],
  );

  const collapseAll = useCallback(() => setExpanded(new Set()), []);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["graph"] });
  const setLive = useMutation({
    mutationFn: (v: { path: string; live: boolean }) => api.liveSet(v.path, v.live),
    onSuccess: invalidate,
  });
  const resetLive = useMutation({
    mutationFn: (mode: "all" | "none") => api.liveReset(mode),
    onSuccess: invalidate,
  });
  const saveUns = useMutation({ mutationFn: (cfg: unknown) => api.unsSave(cfg), onSuccess: invalidate });
  const simulation = useMutation({
    mutationFn: (on: boolean) => (on ? api.simStart() : api.simStop()),
    onSuccess: invalidate,
  });
  const server = useMutation({
    mutationFn: (on: boolean) => (on ? api.serverStart() : api.serverStop()),
    onSuccess: invalidate,
  });
  const bridge = useMutation({
    mutationFn: (on: boolean) => (on ? api.bridgeStart() : api.bridgeStop()),
    onSuccess: invalidate,
  });

  return {
    query,
    graph: query.data,
    expanded,
    toggleExpand,
    collapseAll,
    selectedId,
    setSelectedId,
    selected: selectedId ? byId.get(selectedId) ?? null : null,
    hasChildren,
    childrenOf,
    setLive,
    resetLive,
    saveUns,
    simulation,
    server,
    bridge,
  };
}
