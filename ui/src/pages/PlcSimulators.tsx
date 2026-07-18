import { useRef, useState, type ChangeEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Cpu,
  Play,
  Square,
  Trash2,
  Upload,
  X,
  FileJson,
  Copy,
  Check,
} from "lucide-react";
import { api, type PlcInstance, type PlcImportSummary } from "../api";
import { Page, Card, Field, Button, Toggle, inputCls, cx } from "../components/ui";

/** Simulated "raw" PLC datasources: each instance is its own OPC-UA server
 * built from an imported Kepware / protocol-converter catalog export. */
export function PlcSimulators() {
  const qc = useQueryClient();
  const { data: instances = [] } = useQuery({
    queryKey: ["plc-instances"],
    queryFn: api.plcInstances,
    refetchInterval: 5000,
  });
  const [importOpen, setImportOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ["plc-instances"] });

  const act = async (id: string, fn: () => Promise<{ ok: boolean; msg?: string }>) => {
    setBusy(id);
    setError(null);
    try {
      const r = await fn();
      if (!r.ok) setError(r.msg || "Action failed");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      refresh();
    }
  };

  return (
    <Page
      title="PLC Simulators"
      subtitle="Raw PLC datasources for integration testing — each instance is a standalone OPC-UA server simulating an imported Kepware / PLC tag catalog."
      actions={
        <Button onClick={() => setImportOpen(true)}>
          <span className="flex items-center gap-1.5">
            <Upload size={14} /> Import PLC export
          </span>
        </Button>
      }
    >
      {error && (
        <p className="rounded-lg border border-err/40 bg-err-soft px-3 py-2 text-[12px] text-err">{error}</p>
      )}

      {instances.length === 0 ? (
        <Card
          title="No PLC simulators yet"
          desc="Import an export file to create your first simulated PLC."
          icon={<Cpu size={16} />}
        >
          <div className="text-sm text-fg-muted">
            <p className="mb-2">Supported export formats (auto-detected):</p>
            <ul className="list-disc space-y-1 pl-5 text-[13px]">
              <li>
                <span className="font-medium text-fg">UNS-Protocol-Converter catalog</span> — the{" "}
                <code className="font-mono text-[12px]">catalog_&lt;source&gt;.json</code> browse cache,{" "}
                <code className="font-mono text-[12px]">GET /api/catalog</code> response, or{" "}
                <code className="font-mono text-[12px]">catalog.csv</code>
              </li>
              <li>
                <span className="font-medium text-fg">Native Kepware</span> — JSON project export
                (channels → devices → tag groups) or per-device tag CSV
              </li>
            </ul>
            <p className="mt-3">
              Every tag gets a simulation profile from its name and datatype; repeated structures are
              stamped as UDT instances — ground truth for AI-mapping tests. Writable tags accept and
              hold OPC-UA writes.
            </p>
          </div>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {instances.map((inst) => (
            <InstanceCard key={inst.id} inst={inst} busy={busy === inst.id} act={act} />
          ))}
        </div>
      )}

      {importOpen && (
        <PlcImportModal
          onClose={() => setImportOpen(false)}
          onDone={() => {
            setImportOpen(false);
            refresh();
          }}
        />
      )}
    </Page>
  );
}

function InstanceCard({
  inst,
  busy,
  act,
}: {
  inst: PlcInstance;
  busy: boolean;
  act: (id: string, fn: () => Promise<{ ok: boolean; msg?: string }>) => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const copyEndpoint = async () => {
    try {
      await navigator.clipboard.writeText(inst.endpoint);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <section className="flex flex-col rounded-xl border border-border bg-surface shadow-card">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <span
          className={cx(
            "grid h-8 w-8 shrink-0 place-items-center rounded-lg",
            inst.running ? "bg-ok-soft text-ok" : "bg-surface-2 text-fg-faint",
          )}
        >
          <Cpu size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-fg">{inst.name}</h3>
          <p className="text-[11px] text-fg-muted">
            {inst.tags} tags · {inst.nodes} nodes
            {inst.udtInstances > 0 && ` · ${inst.udtInstances} UDT instances`}
          </p>
        </div>
        <span
          className={cx(
            "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            inst.running ? "bg-ok-soft text-ok" : "bg-surface-2 text-fg-faint",
          )}
        >
          {inst.running ? "Running" : "Stopped"}
        </span>
      </header>

      <div className="flex-1 px-4 py-3">
        <button
          onClick={copyEndpoint}
          title="Copy endpoint"
          className="flex w-full items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1.5 text-left font-mono text-[11px] text-fg-muted hover:text-fg"
        >
          <span className="truncate">{inst.endpoint}</span>
          {copied ? <Check size={12} className="ml-auto shrink-0 text-ok" /> : <Copy size={12} className="ml-auto shrink-0" />}
        </button>
        <div className="mt-2 flex items-center justify-between text-[12px] text-fg-muted">
          <span>Start with dashboard</span>
          <Toggle
            on={inst.autostart}
            onChange={(next) => act(inst.id, () => api.plcPatch(inst.id, { autostart: next }))}
            disabled={busy}
          />
        </div>
      </div>

      <footer className="flex items-center gap-2 border-t border-border px-4 py-3">
        {inst.running ? (
          <Button variant="ghost" disabled={busy} onClick={() => act(inst.id, () => api.plcStop(inst.id))}>
            <span className="flex items-center gap-1.5">
              <Square size={13} /> Stop
            </span>
          </Button>
        ) : (
          <Button disabled={busy} onClick={() => act(inst.id, () => api.plcStart(inst.id))}>
            <span className="flex items-center gap-1.5">
              <Play size={13} /> Start
            </span>
          </Button>
        )}
        <button
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Delete PLC simulator "${inst.name}" and its config?`)) {
              void act(inst.id, () => api.plcDelete(inst.id));
            }
          }}
          className="ml-auto rounded-lg p-2 text-fg-faint hover:bg-surface-2 hover:text-err disabled:opacity-50"
          title="Delete instance"
        >
          <Trash2 size={14} />
        </button>
      </footer>
    </section>
  );
}

function PlcImportModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [port, setPort] = useState("");
  const [files, setFiles] = useState<Array<{ filename: string; content: string }>>([]);
  const [err, setErr] = useState<string | null>(null);
  const [summary, setSummary] = useState<PlcImportSummary | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const importMut = useMutation({
    mutationFn: () =>
      api.plcImport({
        name: name.trim() || files[0]?.filename.replace(/\.[^.]+$/, "") || "PLC-Sim",
        port: port.trim() ? Number(port) : undefined,
        files,
      }),
    onSuccess: (r) => {
      if (!r.ok) {
        setErr(r.msg || "Import failed");
        return;
      }
      setSummary(r.summary ?? null);
    },
    onError: (e) => setErr((e as Error).message),
  });

  const loadFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!picked.length) return;
    setErr(null);
    const loaded = await Promise.all(picked.map(async (f) => ({ filename: f.name, content: await f.text() })));
    setFiles((prev) => [...prev, ...loaded]);
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="rise-in flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Upload size={16} className="text-accent" />
          <h3 className="text-sm font-semibold text-fg">Import PLC export</h3>
          <button onClick={onClose} className="ml-auto text-fg-faint hover:text-fg">
            <X size={16} />
          </button>
        </div>

        {summary ? (
          <div className="flex flex-col gap-3 p-4">
            <p className="text-sm text-fg">
              Imported <span className="font-semibold">{summary.tags}</span> tags across{" "}
              <span className="font-semibold">{summary.nodes}</span> nodes ({summary.devices} devices,{" "}
              {summary.udt_nodes} UDT instances).
            </p>
            {Object.keys(summary.unknown_datatypes).length > 0 && (
              <p className="rounded-lg bg-warn-soft px-3 py-2 text-[12px] text-warn">
                Unknown datatypes mapped to Float: {Object.keys(summary.unknown_datatypes).join(", ")}
              </p>
            )}
            <div className="flex justify-end">
              <Button onClick={onDone}>Done</Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
              <input
                ref={fileRef}
                type="file"
                accept="application/json,.json,.csv,text/csv"
                multiple
                className="hidden"
                onChange={loadFiles}
              />
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={() => fileRef.current?.click()}>
                  <span className="flex items-center gap-1.5">
                    <FileJson size={14} /> Browse…
                  </span>
                </Button>
                <span className="text-[12px] text-fg-muted">
                  Converter catalog (JSON/CSV) or Kepware export (JSON/CSV) — multiple files merge into one PLC.
                </span>
              </div>

              {files.length > 0 && (
                <ul className="flex flex-col gap-1">
                  {files.map((f, i) => (
                    <li
                      key={`${f.filename}-${i}`}
                      className="flex items-center gap-2 rounded-lg bg-surface-2 px-2.5 py-1.5 text-[12px] text-fg"
                    >
                      <FileJson size={13} className="shrink-0 text-accent" />
                      <span className="truncate">{f.filename}</span>
                      <button
                        onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                        className="ml-auto text-fg-faint hover:text-err"
                      >
                        <X size={13} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <div className="grid grid-cols-2 gap-3">
                <Field label="Instance name">
                  <input
                    className={inputCls}
                    placeholder="e.g. Kepware-Line3"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </Field>
                <Field label="OPC-UA port" hint="Leave empty for the next free port (4841+)">
                  <input
                    className={inputCls}
                    placeholder="auto"
                    inputMode="numeric"
                    value={port}
                    onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))}
                  />
                </Field>
              </div>

              {err && <p className="text-[12px] text-err">{err}</p>}
            </div>

            <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={() => importMut.mutate()} disabled={files.length === 0 || importMut.isPending}>
                {importMut.isPending ? "Importing…" : "Import"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
