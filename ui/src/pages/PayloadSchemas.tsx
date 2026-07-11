import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FileJson, Plus, Trash2, X, Check, Loader2 } from "lucide-react";
import { api, type PayloadSchema, type SchemaField } from "../api";
import { Page, Button, inputCls, cx } from "../components/ui";

// Sample values used to render the live JSON preview (mirrors the legacy page).
const SAMPLE: Record<string, unknown> = {
  value: 42.5,
  ts_epoch: 1713523200,
  ts_ms: 1713523200000,
  ts_iso: "2024-04-19T12:00:00.000Z",
  quality: "good",
  is_good: true,
  quality_code: 192,
  unit: "kW",
  dataType: "Float",
  tagName: "CurrentPowerkW",
  topicPath: "GlobalFoodCo.CrispCraft.Antwerp.ProductionLine.Energy.CurrentPowerkW",
  siteName: "Antwerp",
  workCenterName: "Energy",
};

const SOURCES: Array<[string, string]> = [
  ["value", "value — raw tag value"],
  ["ts_epoch", "ts_epoch — Unix timestamp (s)"],
  ["ts_ms", "ts_ms — Unix timestamp (ms)"],
  ["ts_iso", "ts_iso — ISO 8601 string"],
  ["quality", "quality — 'good'/'bad'"],
  ["is_good", "is_good — true/false"],
  ["quality_code", "quality_code — 192/0 (OPC-UA)"],
  ["unit", "unit — engineering unit"],
  ["dataType", "dataType — tag data type"],
  ["tagName", "tagName — last topic segment"],
  ["topicPath", "topicPath — full topic string"],
  ["siteName", "siteName — site name"],
  ["workCenterName", "workCenterName — work center name"],
  ["static", "static — fixed value"],
];

function buildPreview(schema: PayloadSchema | undefined): string {
  if (!schema || !schema.fields.length) return "{}";
  const obj: Record<string, unknown> = {};
  for (const f of schema.fields) {
    if (!f.key) continue;
    if (f.source === "static") {
      const raw = f.staticVal;
      if (raw === "true") obj[f.key] = true;
      else if (raw === "false") obj[f.key] = false;
      else if (raw !== "" && !isNaN(Number(raw))) obj[f.key] = Number(raw);
      else obj[f.key] = raw;
    } else {
      obj[f.key] = SAMPLE[f.source] ?? null;
    }
  }
  return JSON.stringify(obj, null, 2);
}

export function PayloadSchemas() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["payload-schemas"], queryFn: api.payloadSchemas });

  const [schemas, setSchemas] = useState<PayloadSchema[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (data && !loaded) {
      const list = data.schemas ?? [];
      setSchemas(list);
      setActiveId(list[0]?.id ?? null);
      setLoaded(true);
    }
  }, [data, loaded]);

  const active = useMemo(() => schemas.find((s) => s.id === activeId), [schemas, activeId]);

  const save = useMutation({
    mutationFn: () => api.payloadSchemasSave(schemas),
    onSuccess: () => {
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["payload-schemas"] });
    },
  });

  const mutate = (fn: (draft: PayloadSchema[]) => PayloadSchema[]) => {
    setSchemas((prev) => fn(structuredClone(prev)));
    setDirty(true);
  };

  const addSchema = () => {
    const s: PayloadSchema = { id: "schema-" + Date.now(), name: "New Schema", description: "", fields: [] };
    mutate((d) => [...d, s]);
    setActiveId(s.id);
  };
  const delSchema = (id: string) => {
    mutate((d) => d.filter((s) => s.id !== id));
    if (activeId === id) setActiveId(null);
  };
  const patchActive = (patch: Partial<PayloadSchema>) =>
    mutate((d) => d.map((s) => (s.id === activeId ? { ...s, ...patch } : s)));
  const patchField = (idx: number, patch: Partial<SchemaField>) =>
    patchActive({
      fields: (active?.fields ?? []).map((f, i) => (i === idx ? { ...f, ...patch } : f)),
    });
  const addField = () =>
    patchActive({ fields: [...(active?.fields ?? []), { key: "", source: "value", staticVal: "" }] });
  const delField = (idx: number) =>
    patchActive({ fields: (active?.fields ?? []).filter((_, i) => i !== idx) });

  return (
    <Page
      title="Payload Schemas"
      subtitle="Shape the JSON published to the broker for downstream systems."
      actions={
        <div className="flex items-center gap-2">
          <span className={cx("text-[12px] font-medium", dirty ? "text-warn" : "text-ok")}>
            {dirty ? "● Unsaved" : "● Saved"}
          </span>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save all"}
          </Button>
        </div>
      }
    >
      <div className="flex min-h-[520px] gap-4">
        {/* schema list */}
        <div className="flex w-56 shrink-0 flex-col rounded-xl border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-sm font-semibold text-fg">Schemas</span>
            <button onClick={addSchema} title="New schema" className="text-fg-muted hover:text-accent">
              <Plus size={16} />
            </button>
          </div>
          <ul className="flex-1 overflow-y-auto p-1.5">
            {schemas.length === 0 && (
              <li className="px-2 py-6 text-center text-[12px] text-fg-muted">No schemas yet.</li>
            )}
            {schemas.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => setActiveId(s.id)}
                  className={cx(
                    "group flex w-full items-center gap-1 rounded-lg px-2 py-1.5 text-left text-sm",
                    s.id === activeId ? "bg-accent-soft text-accent" : "text-fg hover:bg-surface-2",
                  )}
                >
                  <span className="flex-1 truncate">{s.name || "(unnamed)"}</span>
                  <span
                    role="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      delSchema(s.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 hover:text-err"
                  >
                    <X size={13} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        {/* editor + preview */}
        {!active ? (
          <div className="grid flex-1 place-items-center rounded-xl border border-dashed border-border text-center text-fg-muted">
            <div>
              <FileJson size={22} className="mx-auto text-fg-faint" />
              <p className="mt-2 text-sm">Select a schema, or create a new one.</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 gap-4">
            <div className="flex-1 space-y-3">
              <input
                className={cx(inputCls, "text-sm font-semibold")}
                value={active.name}
                onChange={(e) => patchActive({ name: e.target.value })}
                placeholder="Schema name"
              />
              <input
                className={inputCls}
                value={active.description}
                onChange={(e) => patchActive({ description: e.target.value })}
                placeholder="Description (optional)"
              />

              <div className="overflow-hidden rounded-xl border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-fg-muted">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">Key</th>
                      <th className="px-2 py-1.5 text-left font-medium">Source</th>
                      <th className="w-7" />
                    </tr>
                  </thead>
                  <tbody>
                    {active.fields.map((f, i) => (
                      <tr key={i} className="border-t border-border">
                        <td className="px-2 py-1.5 align-top">
                          <input
                            className={cx(inputCls, "h-8")}
                            value={f.key}
                            placeholder="e.g. v"
                            onChange={(e) => patchField(i, { key: e.target.value })}
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <select
                            className={cx(inputCls, "h-8")}
                            value={f.source}
                            onChange={(e) => patchField(i, { source: e.target.value })}
                          >
                            {SOURCES.map(([v, l]) => (
                              <option key={v} value={v}>
                                {l}
                              </option>
                            ))}
                          </select>
                          {f.source === "static" && (
                            <input
                              className={cx(inputCls, "mt-1.5 h-8")}
                              value={f.staticVal}
                              placeholder="fixed value"
                              onChange={(e) => patchField(i, { staticVal: e.target.value })}
                            />
                          )}
                        </td>
                        <td className="px-1 py-1.5 align-top">
                          <button onClick={() => delField(i)} className="mt-1.5 text-fg-faint hover:text-err">
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button
                  onClick={addField}
                  className="flex w-full items-center justify-center gap-1.5 border-t border-border py-2 text-[12px] text-fg-muted hover:bg-surface-2 hover:text-accent"
                >
                  <Plus size={13} /> Add field
                </button>
              </div>
            </div>

            {/* live preview */}
            <div className="flex w-72 shrink-0 flex-col rounded-xl border border-border bg-surface">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                <Check size={14} className="text-ok" />
                <span className="text-sm font-semibold text-fg">Live preview</span>
              </div>
              <pre className="flex-1 overflow-auto p-3 font-mono text-[12px] leading-relaxed text-fg">
                {buildPreview(active)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </Page>
  );
}
