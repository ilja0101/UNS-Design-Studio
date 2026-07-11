import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, Search, Loader2, Wand2, ExternalLink } from "lucide-react";
import { api, type VizEntity, type VizConfig } from "../api";
import { Page, Button, inputCls, cx } from "../components/ui";

// A small glyph per SCADA equipment kind — self-contained emoji so the page
// needs no asset pipeline.
const KIND_ICON: Record<string, string> = {
  tank: "🛢️",
  pump: "💧",
  vessel: "⚗️",
  motor: "🌀",
  valve: "🔩",
  mixer: "🥣",
  reactor: "☢️",
  conveyor: "📦",
  silo: "🏗️",
  heat_exchanger: "♨️",
  compressor: "🗜️",
  boiler: "🔥",
  generic: "⬜",
};

const kindLabel = (k: string) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function Visualization() {
  const { data } = useQuery({ queryKey: ["viz-entities"], queryFn: api.vizEntities });
  const { data: cfg } = useQuery({ queryKey: ["viz-config"], queryFn: api.vizConfig });
  const { data: live } = useQuery({ queryKey: ["viz-values"], queryFn: api.vizValues, refetchInterval: 2000 });

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const kinds = data?.kinds ?? [];
  const entities = data?.entities ?? [];

  const kindOf = (e: VizEntity) => overrides[e.id] ?? e.kind;
  const dirty = Object.keys(overrides).length > 0;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entities.filter(
      (e) => !q || e.name.toLowerCase().includes(q) || e.parentPath.toLowerCase().includes(q),
    );
  }, [entities, search]);

  const mappedCount = entities.filter((e) => e.mapped || overrides[e.id]).length;

  const save = async () => {
    setSaving(true);
    try {
      const base: VizConfig = cfg ?? {};
      const entMap: Record<string, { kind?: string }> = { ...(base.entities ?? {}) };
      for (const [id, kind] of Object.entries(overrides)) entMap[id] = { ...entMap[id], kind };
      await api.vizConfigSave({ ...base, entities: entMap });
      setOverrides({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const autoMap = () => {
    const next: Record<string, string> = {};
    for (const e of entities) if (!e.mapped && e.suggestion && e.suggestion !== e.kind) next[e.id] = e.suggestion;
    setOverrides((o) => ({ ...o, ...next }));
  };

  return (
    <Page
      title="Visualization"
      subtitle="Assign SCADA equipment kinds to discovered entities, then bind live OPC values."
      actions={
        <div className="flex items-center gap-2">
          <span
            className={cx(
              "flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[12px]",
              live?.opc_ready ? "border-ok/40 bg-ok-soft text-ok" : "border-border bg-surface text-fg-muted",
            )}
          >
            <span className={cx("h-1.5 w-1.5 rounded-full", live?.opc_ready ? "bg-ok" : "bg-fg-faint")} />
            {live?.opc_ready ? "OPC live" : "OPC offline"}
          </span>
          {saved && <span className="text-[12px] font-medium text-ok">Saved</span>}
          <Button onClick={save} disabled={saving || !dirty}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : "Save mapping"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
        <LayoutDashboard size={16} className="text-accent" />
        <span className="text-sm text-fg">
          <strong>{mappedCount}</strong> of {entities.length} entities mapped
        </span>
        <Button variant="ghost" onClick={autoMap}>
          <span className="flex items-center gap-1.5"><Wand2 size={14} /> Auto-map by suggestion</span>
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <a
            href="/viz"
            className="flex items-center gap-1 text-[12px] text-fg-muted hover:text-accent"
            title="Open the legacy schematic canvas editor"
          >
            <ExternalLink size={13} /> Schematic canvas (legacy)
          </a>
        </div>
      </div>

      <div className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2">
        <Search size={14} className="text-fg-faint" />
        <input
          className="flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-faint"
          placeholder="Filter equipment…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-[11px] text-fg-muted">{filtered.length} shown</span>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((e) => {
          const kind = kindOf(e);
          const changed = e.id in overrides;
          return (
            <div
              key={e.id}
              className={cx(
                "flex items-center gap-3 rounded-xl border bg-surface px-3 py-2.5",
                changed ? "border-accent" : "border-border",
              )}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-lg">
                {KIND_ICON[kind] ?? KIND_ICON.generic}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-fg" title={e.name}>
                  {e.name}
                </div>
                <div className="truncate font-mono text-[10px] text-fg-faint" title={e.parentPath}>
                  {e.parentPath.replace(/\|/g, " › ")}
                </div>
              </div>
              <select
                value={kind}
                onChange={(ev) => setOverrides((o) => ({ ...o, [e.id]: ev.target.value }))}
                className={cx(inputCls, "h-8 w-32 shrink-0")}
              >
                <option value="generic">Generic</option>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {kindLabel(k)}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <p className="col-span-full py-8 text-center text-sm text-fg-muted">No entities match.</p>
        )}
      </div>
    </Page>
  );
}
