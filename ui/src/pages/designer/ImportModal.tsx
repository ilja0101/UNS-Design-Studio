import { useRef, useState, type ChangeEvent } from "react";
import { X, Upload, FileJson } from "lucide-react";
import { Button, inputCls, cx } from "../../components/ui";

// Import a UNS from a .json file (browse) or pasted text. "Append" merges the
// imported tree's top-level nodes into the current enterprise; otherwise the
// whole UNS is replaced. Matches the legacy /classic editor's import modal.
export function ImportModal({
  onClose,
  onImport,
}: {
  onClose: () => void;
  onImport: (parsed: unknown, merge: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [merge, setMerge] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setFileName(f.name);
    setErr(null);
    setText(await f.text());
  };

  const submit = () => {
    try {
      const parsed = JSON.parse(text.trim());
      const tree = (parsed as { tree?: { name?: string } })?.tree ?? parsed;
      if (!tree || typeof tree !== "object" || !(tree as { name?: string }).name)
        throw new Error('no UNS tree (need a "tree" with a named root node)');
      onImport(parsed, merge);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="rise-in flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Upload size={16} className="text-accent" />
          <h3 className="text-sm font-semibold text-fg">Import UNS</h3>
          <button onClick={onClose} className="ml-auto text-fg-faint hover:text-fg">
            <X size={16} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={loadFile}
          />
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => fileRef.current?.click()}>
              <span className="flex items-center gap-1.5">
                <FileJson size={14} /> Browse…
              </span>
            </Button>
            <span className="truncate text-[12px] text-fg-muted">
              {fileName || "Choose a .json file, or paste below"}
            </span>
          </div>

          <textarea
            className={cx(inputCls, "h-44 resize-none font-mono text-[11px] leading-relaxed")}
            placeholder={'{ "tree": { "name": "Enterprise", "type": "enterprise", "children": [ … ] } }'}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setErr(null);
            }}
          />

          <label className="flex items-start gap-2 rounded-lg border border-border bg-surface-2 p-2.5 text-[12px] text-fg">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={merge}
              onChange={(e) => setMerge(e.target.checked)}
            />
            <span>
              <span className="font-medium">Append to the existing UNS</span>
              <span className="mt-0.5 block text-fg-muted">
                Merge the imported tree's top-level nodes into the current enterprise
                (its wrapper name / namespace / description are ignored). Unchecked =
                replace the whole UNS.
              </span>
            </span>
          </label>

          {err && <p className="text-[12px] text-err">Invalid file: {err}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!text.trim()}>
            {merge ? "Append to UNS" : "Import (replace)"}
          </Button>
        </div>
      </div>
    </div>
  );
}
