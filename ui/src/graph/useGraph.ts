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

  // Accordion expand: opening a node closes its expanded siblings (and any of
  // their descendants), keeping the stage clean.
  const toggleExpand = useCallback(
    (id: string) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        const descendants = (start: string) => {
          const out: string[] = [];
          const stack = [start];
          while (stack.length) {
            const cur = stack.pop()!;
            for (const c of childrenOf.get(cur) ?? []) {
              out.push(c.id);
              stack.push(c.id);
            }
          }
          return out;
        };
        if (next.has(id)) {
          next.delete(id);
          for (const d of descendants(id)) next.delete(d);
        } else {
          const parent = byId.get(id)?.parentId ?? null;
          for (const sib of childrenOf.get(parent ?? "") ?? []) {
            if (sib.id !== id && next.has(sib.id)) {
              next.delete(sib.id);
              for (const d of descendants(sib.id)) next.delete(d);
            }
          }
          next.add(id);
        }
        return next;
      });
    },
    [byId, childrenOf],
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
  };
}
