import { useMemo, useState } from "react";
import { X, Blocks } from "lucide-react";
import type { AssetDef } from "../../api";
import { Button, cx } from "../../components/ui";

export function AssetModal({
  assets,
  onClose,
  onInsert,
}: {
  assets: AssetDef[];
  onClose: () => void;
  onInsert: (asset: AssetDef) => void;
}) {
  const cats = useMemo(() => [...new Set(assets.map((a) => a.category))], [assets]);
  const [cat, setCat] = useState<string | null>(null);
  const [selId, setSelId] = useState<string | null>(null);

  const shown = cat ? assets.filter((a) => a.category === cat) : assets;
  const selected = assets.find((a) => a.id === selId);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="rise-in flex h-[80vh] w-full max-w-4xl flex-col rounded-xl border border-border bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Blocks size={16} className="text-accent" />
          <h3 className="text-sm font-semibold text-fg">Insert asset bundle</h3>
          <button onClick={onClose} className="ml-auto text-fg-faint hover:text-fg">
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

        <div className="flex min-h-0 flex-1">
          <div className="grid flex-1 auto-rows-min grid-cols-2 gap-2 overflow-auto p-3 sm:grid-cols-3">
            {shown.map((a) => (
              <button
                key={a.id}
                onClick={() => setSelId(a.id)}
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
          <div className="w-72 shrink-0 overflow-auto border-l border-border p-3">
            {!selected ? (
              <p className="text-[12px] text-fg-muted">Select an asset to preview its tags.</p>
            ) : (
              <>
                <div className="mb-1 text-sm font-semibold text-fg">
                  {selected.icon} {selected.label}
                </div>
                <p className="mb-3 text-[11px] text-fg-muted">{selected.description}</p>
                <div className="space-y-1">
                  {selected.tags.map((t, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-1.5 rounded-md bg-surface-2 px-2 py-1 text-[11px]">
                      <span className="font-mono text-accent">{t.name}</span>
                      <span className="text-fg-muted">{t.dataType}</span>
                      {t.unit && <span className="text-warn">{t.unit}</span>}
                      {t.simulation?.profile && <span className="ml-auto text-ok">{t.simulation.profile}</span>}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => selected && onInsert(selected)} disabled={!selected}>
            Insert {selected ? `${selected.tags.length} tags` : ""}
          </Button>
        </div>
      </div>
    </div>
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
