import { useEffect, useMemo, useState } from "react";
import { X, Blocks, ArrowRight, KeyRound } from "lucide-react";
import type { AssetDef, UnsNodeType } from "../../api";
import { Button, cx } from "../../components/ui";
import {
  DEFAULT_RAW_OPTIONS,
  RAW_LEVELS,
  RAW_STYLES,
  defaultNodeName,
  optionsForLevel,
  planInsert,
  stylesForLevel,
  suggestInstance,
  type Grouping,
  type InsertPlan,
  type RawLevel,
  type RawOptions,
  type RawStyle,
  type StructureOptions,
} from "./rawify";

export function AssetModal({
  assets,
  existingNames = [],
  existingChildNames = [],
  defaultLevel = "modelled",
  childType,
  onClose,
  onInsert,
}: {
  assets: AssetDef[];
  /** Tag names already in the target node — the inserter avoids colliding. */
  existingNames?: string[];
  /** Child node names already in the target node — same, for the asset's node. */
  existingChildNames?: string[];
  /** Raw OT sources open on "PLC symbolic"; the UNS model opens on "Modelled". */
  defaultLevel?: RawLevel;
  /** Node type an asset's own node gets here (ISA-95 level, or a raw device). */
  childType: UnsNodeType;
  onClose: () => void;
  onInsert: (asset: AssetDef, plan: InsertPlan) => void;
}) {
  const cats = useMemo(() => [...new Set(assets.map((a) => a.category))], [assets]);
  const [cat, setCat] = useState<string | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const [raw, setRaw] = useState<RawOptions>(() =>
    optionsForLevel(defaultLevel, { ...DEFAULT_RAW_OPTIONS, level: defaultLevel }),
  );
  const [instanceTouched, setInstanceTouched] = useState(false);
  const [createNode, setCreateNode] = useState(true);
  const [nodeName, setNodeName] = useState("");
  const [nodeTouched, setNodeTouched] = useState(false);
  const [grouping, setGrouping] = useState<Grouping>("flat");

  const shown = cat ? assets.filter((a) => a.category === cat) : assets;
  const selected = assets.find((a) => a.id === selId);

  // The loop tag follows the asset family until the user types their own.
  useEffect(() => {
    if (selected && !instanceTouched)
      setRaw((r) => ({ ...r, instance: suggestInstance(selected.id) }));
  }, [selected, instanceTouched]);

  // So does the node name — "P101" for a raw source, "CentrifugalPump" for the UNS.
  useEffect(() => {
    if (selected && !nodeTouched) setNodeName(defaultNodeName(selected, raw, raw.level));
  }, [selected, nodeTouched, raw]);

  const struct: StructureOptions = { createNode, nodeName, nodeType: childType, grouping };
  const result = useMemo(
    () => (selected ? planInsert(selected, raw, struct, existingNames, existingChildNames) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selected, raw, createNode, nodeName, childType, grouping, existingNames, existingChildNames],
  );

  const levelMeta = RAW_LEVELS.find((l) => l.id === raw.level)!;
  // Bundle order, so each preview row describes its own tag even when grouping
  // has scattered them into folders.
  const previewTags = result?.orderedTags ?? [];
  const modelled = raw.level === "modelled";
  const addressed = raw.level === "address";
  const siemensAddr = addressed && (raw.style === "siemens" || raw.style === "kepware" || raw.style === "isa");

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="rise-in flex h-[85vh] w-full max-w-5xl flex-col rounded-xl border border-border bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Blocks size={16} className="text-accent" />
          <h3 className="text-sm font-semibold text-fg">Insert asset bundle</h3>
          <button onClick={onClose} aria-label="Close" className="ml-auto text-fg-faint hover:text-fg">
            <X size={16} />
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5 border-b border-border px-4 py-2">
          <CatBtn on={cat === null} onClick={() => setCat(null)}>
            All
          </CatBtn>
          {cats.map((c) => (
            <CatBtn key={c} on={cat === c} onClick={() => setCat(c)}>
              {c}
            </CatBtn>
          ))}
        </div>

        {/* rawness */}
        <div className="border-b border-border bg-surface-2/50 px-4 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-fg-muted">Rawness</span>
            <div className="flex overflow-hidden rounded-lg border border-border">
              {RAW_LEVELS.map((l) => (
                <button
                  key={l.id}
                  onClick={() => setRaw((r) => optionsForLevel(l.id, r))}
                  title={l.hint}
                  aria-label={`Rawness: ${l.label}`}
                  aria-pressed={raw.level === l.id}
                  className={cx(
                    "px-2.5 py-1 text-[12px] font-medium",
                    raw.level === l.id ? "bg-accent text-accent-fg" : "bg-surface text-fg-muted hover:text-fg",
                  )}
                >
                  {l.label}
                </button>
              ))}
            </div>
            <span className="text-[11px] text-fg-muted">{levelMeta.hint}</span>
          </div>

          {!modelled && (
            <div className="mt-2 flex flex-wrap items-end gap-3">
              <Small label="Instance / loop tag">
                <input
                  className="h-7 w-28 rounded-md border border-border bg-bg px-2 font-mono text-[12px] text-fg outline-none focus:border-accent"
                  value={raw.instance}
                  onChange={(e) => {
                    setInstanceTouched(true);
                    setRaw((r) => ({ ...r, instance: e.target.value }));
                  }}
                />
              </Small>

              {raw.level !== "flat" && (
                <Small label="Convention">
                  <select
                    className="h-7 rounded-md border border-border bg-bg px-1.5 text-[12px] text-fg outline-none focus:border-accent"
                    value={raw.style}
                    onChange={(e) => setRaw((r) => ({ ...r, style: e.target.value as RawStyle }))}
                  >
                    {stylesForLevel(raw.level).map((id) => (
                      <option key={id} value={id}>
                        {RAW_STYLES.find((s) => s.id === id)!.label}
                      </option>
                    ))}
                  </select>
                </Small>
              )}

              {siemensAddr && (
                <Small label="DB">
                  <NumIn value={raw.db} onChange={(v) => setRaw((r) => ({ ...r, db: v }))} width="w-16" />
                </Small>
              )}
              {addressed && (
                <Small label="Start offset">
                  <NumIn value={raw.address} onChange={(v) => setRaw((r) => ({ ...r, address: v }))} width="w-20" />
                </Small>
              )}
              <Small label="Spare tags">
                <NumIn value={raw.spares} onChange={(v) => setRaw((r) => ({ ...r, spares: v }))} width="w-16" />
              </Small>

              {addressed && (
                <Check
                  on={raw.rawCounts}
                  onChange={(v) => setRaw((r) => ({ ...r, rawCounts: v }))}
                  label="Raw counts"
                  title="Analogs become integer PLC counts (0–27648 / 0–4095); the scaling is left for the mapper to work out."
                />
              )}
              <Check
                on={raw.keepUnits}
                onChange={(v) => setRaw((r) => ({ ...r, keepUnits: v }))}
                label="Keep units"
              />
              <Check
                on={raw.keepDescriptions}
                onChange={(v) => setRaw((r) => ({ ...r, keepDescriptions: v }))}
                label="Keep descriptions"
              />
              <Check
                on={raw.truth}
                onChange={(v) => setRaw((r) => ({ ...r, truth: v }))}
                label="Answer key"
                title="Store what each mangled tag really is, so a mapping run can be scored later. Never exposed over OPC-UA."
              />
            </div>
          )}
        </div>

        {/* structure */}
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-2">
          <span className="pb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">Structure</span>
          <Check
            on={createNode}
            onChange={setCreateNode}
            label="Give the asset its own node"
            title="Off: the tags are appended straight into the selected node."
          />
          {createNode && (
            <>
              <Small label="Node name">
                <input
                  className="h-7 w-40 rounded-md border border-border bg-bg px-2 font-mono text-[12px] text-fg outline-none focus:border-accent"
                  value={nodeName}
                  onChange={(e) => {
                    setNodeTouched(true);
                    setNodeName(e.target.value);
                  }}
                />
              </Small>
              <Small label="Tag folders">
                <select
                  className="h-7 rounded-md border border-border bg-bg px-1.5 text-[12px] text-fg outline-none focus:border-accent"
                  value={grouping}
                  onChange={(e) => setGrouping(e.target.value as Grouping)}
                >
                  <option value="flat">All tags in the node</option>
                  <option value="kind">Group by function</option>
                </select>
              </Small>
            </>
          )}
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="grid flex-1 auto-rows-min grid-cols-2 gap-2 overflow-auto p-3 sm:grid-cols-3">
            {shown.map((a) => (
              <button
                key={a.id}
                onClick={() => setSelId(a.id)}
                aria-label={a.label}
                aria-pressed={selId === a.id}
                className={cx(
                  "flex flex-col items-start rounded-xl border p-3 text-left transition-tokens",
                  selId === a.id ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-accent",
                )}
              >
                <span className="text-xl">{a.icon || "📦"}</span>
                <span className="mt-1 text-sm font-medium text-fg">{a.label}</span>
                <span className="text-[11px] text-fg-muted">{a.category}</span>
                <span className="mt-1 text-[10px] text-fg-faint">
                  {a.tags.length} tag{a.tags.length !== 1 ? "s" : ""}
                </span>
              </button>
            ))}
            {shown.length === 0 && <p className="col-span-full p-4 text-sm text-fg-muted">No assets in this category.</p>}
          </div>

          {/* preview */}
          <div className="w-80 shrink-0 overflow-auto border-l border-border p-3">
            {!selected || !result ? (
              <p className="text-[12px] text-fg-muted">Select an asset to preview its tags.</p>
            ) : (
              <>
                <div className="mb-1 text-sm font-semibold text-fg">
                  {selected.icon} {selected.label}
                </div>
                <p className="mb-3 text-[11px] text-fg-muted">{selected.description}</p>
                <div className="space-y-1">
                  {result.preview.map((row, i) => (
                    <div key={i} className="rounded-md bg-surface-2 px-2 py-1 text-[11px]">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {!modelled && row.from !== row.to && (
                          <>
                            <span className="font-mono text-fg-faint line-through">{row.from}</span>
                            <ArrowRight size={10} className="text-fg-faint" />
                          </>
                        )}
                        <span className="font-mono text-accent">{row.to}</span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-fg-muted">
                        {createNode && grouping === "kind" && (
                          <span className="text-fg-faint">{result.groups[i]}/</span>
                        )}
                        <span>{row.dataType}</span>
                        {row.unit && <span className="text-warn">{row.unit}</span>}
                        {previewTags[i]?.simulation?.rawScale && (
                          <span className="text-fg-faint">
                            counts 0–{previewTags[i].simulation!.rawScale!.rawHi}
                          </span>
                        )}
                        {previewTags[i]?._truth?.decoy && <span className="ml-auto text-err">spare</span>}
                      </div>
                    </div>
                  ))}
                </div>
                {raw.truth && !modelled && (
                  <p className="mt-3 flex items-start gap-1.5 text-[11px] text-fg-muted">
                    <KeyRound size={12} className="mt-0.5 shrink-0 text-ok" />
                    Answer key stored with each tag — download it from the PLC Simulators page to score a mapping run.
                  </p>
                )}
              </>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          {selected && result && (
            <span className="mr-auto text-[11px] text-fg-muted">
              {previewTags.length} tags
              {result.node ? ` in node "${result.node.name}"` : " in this node"}
              {result.folderCount ? ` · ${result.folderCount} folders` : ""} · {levelMeta.label}
              {!modelled && raw.level !== "flat" ? ` · ${RAW_STYLES.find((s) => s.id === raw.style)?.label}` : ""}
            </span>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => selected && result && onInsert(selected, result)} disabled={!selected}>
            Insert {result ? `${previewTags.length} tags` : ""}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Small({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      {children}
    </label>
  );
}

function NumIn({
  value,
  onChange,
  width = "w-20",
}: {
  value: number;
  onChange: (v: number) => void;
  width?: string;
}) {
  return (
    <input
      type="number"
      className={cx(
        width,
        "h-7 rounded-md border border-border bg-bg px-2 font-mono text-[12px] text-fg outline-none focus:border-accent",
      )}
      value={value}
      onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
    />
  );
}

function Check({
  on,
  onChange,
  label,
  title,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  label: string;
  title?: string;
}) {
  return (
    <label title={title} className="flex cursor-pointer items-center gap-1.5 pb-1 text-[12px] text-fg-muted">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-[var(--accent)]"
      />
      {label}
    </label>
  );
}

function CatBtn({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cx(
        "rounded-lg border px-2.5 py-1 text-[12px] font-medium",
        on ? "border-accent bg-accent text-accent-fg" : "border-border bg-surface text-fg-muted hover:border-accent",
      )}
    >
      {children}
    </button>
  );
}
