import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  Plus,
  Copy,
  Trash2,
  Save,
  FolderTree,
  ListTree,
  Tags,
  Route,
  ScrollText,
  Blocks,
  Search,
  ChevronsDownUp,
  ChevronsUpDown,
  Download,
  Upload,
  Eraser,
} from "lucide-react";
import { api, type UnsConfig, type UnsTreeNode, type UnsTag, type AssetDef } from "../../api";
import { Button, inputCls, cx } from "../../components/ui";
import {
  NT,
  NODE_ORDER,
  find,
  findParent,
  topicPath,
  allTagPaths,
  countNodes,
  countTags,
  maxDepth,
  subtreeMatch,
  newTag,
  newNode,
  reId,
  uid,
  plantKey,
} from "./tree";
import { SimModal } from "./SimModal";
import { AssetModal } from "./AssetModal";
import { ImportModal } from "./ImportModal";

type Tab = "props" | "tags" | "paths" | "recipes";

export function Designer() {
  const [cfg, setCfg] = useState<UnsConfig | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [dirty, setDirty] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("props");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ text: string; tone: "ok" | "err" } | null>(null);
  const [simTagIdx, setSimTagIdx] = useState<number | null>(null);
  const [assetOpen, setAssetOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const { data: loaded } = useQuery({ queryKey: ["uns-config"], queryFn: api.unsConfig });
  const { data: profiles } = useQuery({ queryKey: ["sim-profiles"], queryFn: api.simulationProfiles });
  const { data: assetLib } = useQuery({ queryKey: ["asset-lib"], queryFn: api.assetLibraryFull });
  const { data: schemas } = useQuery({ queryKey: ["payload-schemas"], queryFn: api.payloadSchemas });

  useEffect(() => {
    if (loaded && !cfg) {
      setCfg(loaded);
      setExpanded(new Set([loaded.tree.id]));
    }
  }, [loaded, cfg]);

  const flash = (text: string, tone: "ok" | "err" = "ok") => {
    setToast({ text, tone });
    setTimeout(() => setToast(null), 2400);
  };

  // ── Import / Export / Clear ──
  const exportJson = () => {
    if (!cfg) return;
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${cfg.tree?.name || "uns"}_uns_config.json`;
    a.click();
    URL.revokeObjectURL(url);
    flash("Exported uns_config.json");
  };

  // Import from the modal. merge=true appends the imported tree's top-level
  // nodes into the current enterprise (its wrapper is ignored); merge=false
  // replaces the whole UNS. Every imported node/tag is re-keyed (reId) so a
  // null/duplicate id can't break node selection.
  const applyImport = (parsed: unknown, merge: boolean) => {
    try {
      const p = parsed as Partial<UnsConfig> & { name?: string };
      const rawTree = (p.tree ?? (parsed as UnsTreeNode)) as UnsTreeNode;
      if (!rawTree || typeof rawTree !== "object" || !rawTree.name)
        throw new Error("no UNS tree (missing a named root node)");

      if (merge && cfg?.tree) {
        const incoming = (rawTree.children ?? []).map((c) => reId(c));
        if (!incoming.length) throw new Error("nothing to append — imported tree has no child nodes");
        const existing = new Set((cfg.tree.children ?? []).map((c) => c.name));
        const clash = incoming.map((c) => c.name).filter((n) => existing.has(n));
        if (clash.length && !confirm(`Duplicate top-level node name(s) will be created: ${clash.join(", ")}.\nAppend anyway?`))
          return;
        const rootId = cfg.tree.id;
        mutate((d) => {
          d.tree.children = [...(d.tree.children ?? []), ...incoming];
        });
        setExpanded((prev) => new Set(prev).add(rootId));
        flash(`Appended ${incoming.length} node(s) — review and Save`);
      } else {
        const next: UnsConfig = {
          version: p.version,
          namespaceUri: p.namespaceUri,
          description: p.description,
          tree: reId(rawTree),
        };
        setCfg(next);
        setExpanded(new Set([next.tree.id]));
        setDirty(true);
        flash(`Imported "${next.tree.name}" — review and Save`);
      }
      setSelId(null);
      setImportOpen(false);
    } catch (err) {
      flash("Import failed: " + (err as Error).message, "err");
    }
  };

  const clearTree = () => {
    if (!confirm("Clear the entire UNS tree? All nodes and tags will be removed.\nSave to make it permanent.")) return;
    mutate((d) => {
      d.tree = {
        id: uid(),
        name: d.tree?.name || "Enterprise",
        type: "enterprise",
        description: d.tree?.description ?? "",
        tags: [],
        children: [],
      };
    });
    setSelId(null);
    setExpanded(new Set());
    flash("UNS tree cleared — Save to persist");
  };

  const tree = cfg?.tree;
  const selected = useMemo(() => (tree && selId ? find(tree, selId) : null), [tree, selId]);

  // Every mutation clones the whole config, applies a function to the working
  // tree, and marks dirty — keeps React state immutable and undo-friendly.
  const mutate = (fn: (draft: UnsConfig) => void) => {
    setCfg((prev) => {
      if (!prev) return prev;
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
    setDirty(true);
  };
  const mutateNode = (id: string, fn: (n: UnsTreeNode) => void) =>
    mutate((d) => {
      const n = find(d.tree, id);
      if (n) fn(n);
    });

  const profileLabel = (pid: string): string => {
    for (const g of profiles ?? []) {
      const p = g.profiles.find((x) => x.id === pid);
      if (p) return p.label;
    }
    return pid || "—";
  };

  // ── tree ops ──
  const toggle = (id: string) =>
    setExpanded((p) => {
      const n = new Set(p);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const setAll = (open: boolean) => {
    if (!tree) return;
    const s = new Set<string>();
    if (open) {
      const walk = (n: UnsTreeNode) => {
        s.add(n.id);
        (n.children ?? []).forEach(walk);
      };
      walk(tree);
    } else s.add(tree.id);
    setExpanded(s);
  };

  const addChild = (parentId: string, custom = false) => {
    const parent = tree && find(tree, parentId);
    if (!parent) return;
    const type = custom ? "workCenter" : NT[parent.type].next;
    const node = newNode(type);
    mutateNode(parentId, (p) => {
      (p.children ??= []).push(node);
    });
    setExpanded((s) => new Set(s).add(parentId));
    setSelId(node.id);
    setActiveTab("props");
  };
  const duplicate = (id: string) => {
    if (!tree) return;
    const parent = findParent(tree, id);
    const node = find(tree, id);
    if (!parent || !node) {
      flash("Cannot duplicate root", "err");
      return;
    }
    const copy = reId(node);
    copy.name += "_copy";
    mutate((d) => {
      const p = find(d.tree, parent.id)!;
      const idx = (p.children ?? []).findIndex((c) => c.id === id);
      p.children!.splice(idx + 1, 0, copy);
    });
    setSelId(copy.id);
    flash(`Duplicated ${node.name}`);
  };
  const remove = (id: string) => {
    if (!tree || id === tree.id) {
      flash("Cannot delete root", "err");
      return;
    }
    const parent = findParent(tree, id);
    if (!parent) return;
    mutate((d) => {
      const p = find(d.tree, parent.id)!;
      p.children = (p.children ?? []).filter((c) => c.id !== id);
    });
    if (selId === id) setSelId(null);
    flash("Node deleted");
  };

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      const res = await api.unsConfigSave(cfg);
      if (res.ok) {
        setDirty(false);
        const svc = (res.restarted ?? []).join(" + ");
        flash(svc ? `Saved — restarted: ${svc}` : "Saved");
      } else flash("Save failed", "err");
    } catch (e) {
      flash("Save error: " + (e as Error).message, "err");
    } finally {
      setSaving(false);
    }
  };

  if (!cfg || !tree)
    return <div className="grid h-full place-items-center text-sm text-fg-muted">Loading UNS…</div>;

  const nextMeta = selected ? NT[NT[selected.type].next] : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* toolbar */}
      <div className="flex items-center gap-2 border-b border-border bg-surface px-4 py-2">
        <FolderTree size={16} className="text-accent" />
        <span className="text-sm font-semibold text-fg">UNS Designer</span>
        <span className="ml-2 text-xs text-fg-muted">
          {countNodes(tree)} nodes · {countTags(tree)} tags · depth {maxDepth(tree)}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setImportOpen(true)}
            title="Import a UNS from a .json file — replace or append (Save to persist)"
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px] text-fg-muted hover:border-accent hover:text-accent"
          >
            <Upload size={14} /> Import
          </button>
          <button
            onClick={exportJson}
            title="Export the current UNS as uns_config.json"
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px] text-fg-muted hover:border-accent hover:text-accent"
          >
            <Download size={14} /> Export
          </button>
          <button
            onClick={clearTree}
            title="Clear the entire UNS tree (Save to persist)"
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px] text-fg-muted hover:border-err hover:text-err"
          >
            <Eraser size={14} /> Clear
          </button>
          <span className={cx("ml-1 text-[12px] font-medium", dirty ? "text-warn" : "text-ok")}>
            {dirty ? "● Unsaved" : "● Saved"}
          </span>
          <Button onClick={save} disabled={saving || !dirty}>
            <span className="flex items-center gap-1.5">
              <Save size={14} /> {saving ? "Saving…" : "Save"}
            </span>
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* tree panel */}
        <div className="flex w-80 shrink-0 flex-col border-r border-border bg-surface">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search size={14} className="text-fg-faint" />
            <input
              className="flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-faint"
              placeholder="Search nodes & tags…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button onClick={() => setAll(true)} title="Expand all" className="text-fg-faint hover:text-fg">
              <ChevronsUpDown size={15} />
            </button>
            <button onClick={() => setAll(false)} title="Collapse all" className="text-fg-faint hover:text-fg">
              <ChevronsDownUp size={15} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto py-1">
            <TreeRow
              node={tree}
              depth={0}
              search={search}
              expanded={expanded}
              selId={selId}
              onToggle={toggle}
              onSelect={(id) => {
                setSelId(id);
                setActiveTab("props");
              }}
              onAdd={addChild}
              onDup={duplicate}
              onDel={remove}
            />
          </div>
          <div className="border-t border-border p-2">
            <button
              onClick={() => addChild(tree.id)}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-border py-2 text-[12px] text-fg-muted hover:border-accent hover:text-accent"
            >
              <Plus size={13} /> Add {NT[NT[tree.type].next].label} to root
            </button>
          </div>
        </div>

        {/* properties */}
        <div className="min-w-0 flex-1 overflow-auto bg-bg">
          {!selected ? (
            <div className="grid h-full place-items-center text-center text-fg-muted">
              <div>
                <ListTree size={22} className="mx-auto text-fg-faint" />
                <p className="mt-2 text-sm">Select a node to edit its properties, tags and recipes.</p>
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-[1400px] p-6">
              <div className="mb-3 flex items-center gap-2">
                <span
                  className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
                  style={{
                    background: NT[selected.type].color + "22",
                    color: NT[selected.type].color,
                  }}
                >
                  {NT[selected.type].label}
                </span>
                <span className="font-mono text-[11px] text-fg-faint">{topicPath(tree, selected.id)}</span>
                {nextMeta && (
                  <button
                    onClick={() => addChild(selected.id)}
                    className="ml-auto flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-fg-muted hover:border-accent hover:text-accent"
                  >
                    <Plus size={12} /> Add {nextMeta.label}
                  </button>
                )}
              </div>

              {/* tabs */}
              <div className="mb-4 flex gap-1 border-b border-border">
                {(
                  [
                    ["props", "Properties", ListTree],
                    ["tags", `Tags${selected.tags?.length ? ` (${selected.tags.length})` : ""}`, Tags],
                    ["paths", "Paths", Route],
                    ["recipes", "Recipes", ScrollText],
                  ] as const
                ).map(([id, label, Icon]) => (
                  <button
                    key={id}
                    onClick={() => setActiveTab(id)}
                    className={cx(
                      "flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm",
                      activeTab === id
                        ? "border-accent font-medium text-accent"
                        : "border-transparent text-fg-muted hover:text-fg",
                    )}
                  >
                    <Icon size={14} /> {label}
                  </button>
                ))}
              </div>

              {activeTab === "props" && (
                <PropsTab
                  node={selected}
                  onName={(v) => mutateNode(selected.id, (n) => (n.name = v))}
                  onType={(v) => mutateNode(selected.id, (n) => (n.type = v))}
                  onDesc={(v) => mutateNode(selected.id, (n) => (n.description = v))}
                />
              )}

              {activeTab === "tags" && (
                <TagsTab
                  node={selected}
                  schemas={schemas?.schemas ?? []}
                  profileLabel={profileLabel}
                  onAddTag={() =>
                    mutateNode(selected.id, (n) => {
                      (n.tags ??= []).push(newTag());
                    })
                  }
                  onOpenAssets={() => setAssetOpen(true)}
                  onUpdTag={(i, field, val) =>
                    mutateNode(selected.id, (n) => {
                      (n.tags![i] as unknown as Record<string, unknown>)[field] = val;
                    })
                  }
                  onDelTag={(i) =>
                    mutateNode(selected.id, (n) => {
                      n.tags!.splice(i, 1);
                    })
                  }
                  onEditSim={(i) => setSimTagIdx(i)}
                />
              )}

              {activeTab === "paths" && <PathsTab tree={tree} node={selected} />}

              {activeTab === "recipes" && (
                <RecipesTab
                  tree={tree}
                  node={selected}
                  onAdd={() =>
                    mutateNode(selected.id, (n) => {
                      (n.recipes ??= []).push({ name: "New Recipe", params: {} });
                    })
                  }
                  onName={(i, v) =>
                    mutateNode(selected.id, (n) => {
                      n.recipes![i].name = v;
                    })
                  }
                  onDel={(i) =>
                    mutateNode(selected.id, (n) => {
                      n.recipes!.splice(i, 1);
                    })
                  }
                />
              )}
            </div>
          )}
        </div>
      </div>

      {/* modals */}
      {selected && simTagIdx !== null && selected.tags?.[simTagIdx] && (
        <SimModal
          tag={selected.tags[simTagIdx]}
          profiles={profiles ?? []}
          onClose={() => setSimTagIdx(null)}
          onSave={(sim) => {
            mutateNode(selected.id, (n) => (n.tags![simTagIdx].simulation = sim));
            setSimTagIdx(null);
          }}
        />
      )}
      {selected && assetOpen && (
        <AssetModal
          assets={assetLib?.assets ?? []}
          onClose={() => setAssetOpen(false)}
          onInsert={(asset: AssetDef) => {
            mutateNode(selected.id, (n) => {
              n.tags ??= [];
              asset.tags.forEach((t) =>
                n.tags!.push({
                  ...newTag(),
                  ...t,
                  simulation: t.simulation ? { ...t.simulation } : null,
                } as UnsTag),
              );
            });
            setAssetOpen(false);
            setActiveTab("tags");
            flash(`Added ${asset.tags.length} tags from "${asset.label}"`);
          }}
        />
      )}

      {importOpen && <ImportModal onClose={() => setImportOpen(false)} onImport={applyImport} />}

      {toast && (
        <div
          className={cx(
            "rise-in fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg border px-3 py-2 text-sm font-medium shadow-pop",
            toast.tone === "ok" ? "border-ok/40 bg-ok-soft text-ok" : "border-err/40 bg-err-soft text-err",
          )}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}

// ── tree row ──
function TreeRow({
  node,
  depth,
  search,
  expanded,
  selId,
  onToggle,
  onSelect,
  onAdd,
  onDup,
  onDel,
}: {
  node: UnsTreeNode;
  depth: number;
  search: string;
  expanded: Set<string>;
  selId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  onAdd: (id: string) => void;
  onDup: (id: string) => void;
  onDel: (id: string) => void;
}) {
  if (search && !subtreeMatch(node, search)) return null;
  const hasChildren = (node.children ?? []).length > 0;
  const isExp = expanded.has(node.id) || !!search;
  const meta = NT[node.type];

  return (
    <div>
      <div
        onClick={() => onSelect(node.id)}
        className={cx(
          "group flex cursor-pointer items-center gap-1 py-[3px] pr-2 text-sm hover:bg-surface-2",
          selId === node.id && "bg-accent-soft",
        )}
        style={{ paddingLeft: depth * 12 + 6 }}
      >
        {hasChildren ? (
          <ChevronRight
            size={13}
            className={cx("shrink-0 text-fg-faint transition-transform", isExp && "rotate-90")}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.id);
            }}
          />
        ) : (
          <span className="w-[13px] shrink-0" />
        )}
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: meta.color }} />
        <span className="truncate text-fg">{node.name}</span>
        {(node.tags ?? []).length > 0 && (
          <span className="rounded bg-surface-2 px-1 text-[9px] text-fg-muted">{node.tags!.length}t</span>
        )}
        <span className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100">
          <button title="Add child" onClick={(e) => { e.stopPropagation(); onAdd(node.id); }} className="text-fg-faint hover:text-accent">
            <Plus size={13} />
          </button>
          <button title="Duplicate" onClick={(e) => { e.stopPropagation(); onDup(node.id); }} className="text-fg-faint hover:text-fg">
            <Copy size={12} />
          </button>
          <button title="Delete" onClick={(e) => { e.stopPropagation(); onDel(node.id); }} className="text-fg-faint hover:text-err">
            <Trash2 size={12} />
          </button>
        </span>
      </div>
      {isExp &&
        (node.children ?? []).map((c) => (
          <TreeRow
            key={c.id}
            node={c}
            depth={depth + 1}
            search={search}
            expanded={expanded}
            selId={selId}
            onToggle={onToggle}
            onSelect={onSelect}
            onAdd={onAdd}
            onDup={onDup}
            onDel={onDel}
          />
        ))}
    </div>
  );
}

// ── Properties tab ──
function PropsTab({
  node,
  onName,
  onType,
  onDesc,
}: {
  node: UnsTreeNode;
  onName: (v: string) => void;
  onType: (v: UnsTreeNode["type"]) => void;
  onDesc: (v: string) => void;
}) {
  return (
    <div className="grid max-w-lg gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-[12px] font-medium text-fg-muted">Name</span>
        <input className={inputCls} value={node.name} onChange={(e) => onName(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[12px] font-medium text-fg-muted">Type</span>
        <select className={inputCls} value={node.type} onChange={(e) => onType(e.target.value as UnsTreeNode["type"])}>
          {NODE_ORDER.map((t) => (
            <option key={t} value={t}>
              {NT[t].label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[12px] font-medium text-fg-muted">Description</span>
        <textarea
          className={cx(inputCls, "h-20 resize-y py-2")}
          value={node.description ?? ""}
          onChange={(e) => onDesc(e.target.value)}
        />
      </label>
    </div>
  );
}

// ── Tags tab ──
function TagsTab({
  node,
  schemas,
  profileLabel,
  onAddTag,
  onOpenAssets,
  onUpdTag,
  onDelTag,
  onEditSim,
}: {
  node: UnsTreeNode;
  schemas: Array<{ id: string; name: string }>;
  profileLabel: (id: string) => string;
  onAddTag: () => void;
  onOpenAssets: () => void;
  onUpdTag: (i: number, field: string, val: string) => void;
  onDelTag: (i: number) => void;
  onEditSim: (i: number) => void;
}) {
  const tags = node.tags ?? [];
  return (
    <div>
      <div className="mb-3 flex gap-2">
        <Button onClick={onAddTag}>
          <span className="flex items-center gap-1.5"><Plus size={14} /> Add tag</span>
        </Button>
        <Button variant="ghost" onClick={onOpenAssets}>
          <span className="flex items-center gap-1.5"><Blocks size={14} /> Insert asset bundle</span>
        </Button>
      </div>
      {tags.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-fg-muted">
          No tags yet. Add individual data points, or insert a pre-configured asset bundle.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-fg-muted">
              <tr>
                {["Name", "Type", "Unit", "Access", "Payload schema", "Simulation", "Description", ""].map((h) => (
                  <th key={h} className="px-2 py-1.5 text-left font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tags.map((t, i) => (
                <tr key={t.id} className="border-t border-border">
                  <td className="px-2 py-1.5">
                    <input className={cx(inputCls, "h-8 min-w-[110px]")} value={t.name} onChange={(e) => onUpdTag(i, "name", e.target.value)} />
                  </td>
                  <td className="px-2 py-1.5">
                    <select className={cx(inputCls, "h-8")} value={t.dataType} onChange={(e) => onUpdTag(i, "dataType", e.target.value)}>
                      {["Float", "Int", "Bool", "String", "DateTime"].map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    <input className={cx(inputCls, "h-8 w-16")} value={t.unit} onChange={(e) => onUpdTag(i, "unit", e.target.value)} />
                  </td>
                  <td className="px-2 py-1.5">
                    <select className={cx(inputCls, "h-8")} value={t.access} onChange={(e) => onUpdTag(i, "access", e.target.value)}>
                      {["R", "RW", "W"].map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    <select className={cx(inputCls, "h-8")} value={t.payloadSchema} onChange={(e) => onUpdTag(i, "payloadSchema", e.target.value)}>
                      <option value="">— default —</option>
                      {schemas.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    <button
                      onClick={() => onEditSim(i)}
                      className={cx(
                        "flex items-center gap-1 rounded-md px-2 py-1 text-[12px]",
                        t.simulation?.profile ? "text-ok hover:bg-ok-soft" : "text-fg-faint hover:bg-surface-2",
                      )}
                    >
                      {t.simulation?.profile ? profileLabel(t.simulation.profile) : "— set profile"} ✏️
                    </button>
                  </td>
                  <td className="px-2 py-1.5">
                    <input className={cx(inputCls, "h-8 min-w-[120px]")} value={t.description} onChange={(e) => onUpdTag(i, "description", e.target.value)} />
                  </td>
                  <td className="px-1 py-1.5">
                    <button onClick={() => onDelTag(i)} className="text-fg-faint hover:text-err">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Paths tab ──
function PathsTab({ tree, node }: { tree: UnsTreeNode; node: UnsTreeNode }) {
  const full = topicPath(tree, node.id);
  const parentPath = full.includes("/") ? full.slice(0, full.lastIndexOf("/")) : "";
  const paths = allTagPaths(node, parentPath);
  return (
    <div>
      <div className="mb-2 text-[12px] text-fg-muted">{paths.length} path{paths.length !== 1 ? "s" : ""}</div>
      {paths.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-fg-muted">
          No tags in this subtree.
        </div>
      ) : (
        <div className="space-y-0.5 rounded-xl border border-border bg-surface p-2 font-mono text-[12px]">
          {paths.map((p) => {
            const parts = p.split("/");
            const tag = parts.pop();
            return (
              <div key={p} className="truncate">
                <span className="text-fg-faint">{parts.join("/")}/</span>
                <span className="text-accent">{tag}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Recipes tab ──
function RecipesTab({
  tree,
  node,
  onAdd,
  onName,
  onDel,
}: {
  tree: UnsTreeNode;
  node: UnsTreeNode;
  onAdd: () => void;
  onName: (i: number, v: string) => void;
  onDel: (i: number) => void;
}) {
  const key = plantKey(tree, node);
  const [active, setActive] = useState("");
  useEffect(() => {
    if (!key) return;
    const [group, plant] = key.split("|");
    api.recipes(group, plant).then((d) => setActive(d.active ?? "")).catch(() => setActive(""));
  }, [key]);

  if (node.type !== "site") {
    return (
      <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-fg-muted">
        Recipes are defined on <span className="font-medium text-fg">site</span> nodes. Select a site to edit its recipes.
      </div>
    );
  }
  const recipes = node.recipes ?? [];
  return (
    <div className="max-w-lg">
      <Button onClick={onAdd}>
        <span className="flex items-center gap-1.5"><Plus size={14} /> Add recipe</span>
      </Button>
      <div className="mt-3 space-y-2">
        {recipes.length === 0 && <p className="text-sm text-fg-muted">No recipes defined.</p>}
        {recipes.map((r, i) => (
          <div key={i} className="flex items-center gap-2">
            <input className={cx(inputCls, "flex-1")} value={r.name} onChange={(e) => onName(i, e.target.value)} />
            {r.name === active && (
              <span className="rounded bg-ok-soft px-2 py-1 text-[11px] font-medium text-ok">● active</span>
            )}
            <button onClick={() => onDel(i)} className="text-fg-faint hover:text-err">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
