import { useState } from "react";
import { Cpu, X } from "lucide-react";
import { api, type PlcInstance } from "../../api";
import { Button, inputCls } from "../../components/ui";

/** Create an empty raw OT source — a PLC sim with nothing in it yet.
 *  The Designer then fills it from the asset library, at whatever rawness. */
export function NewSourceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (instance: PlcInstance) => void;
}) {
  const [name, setName] = useState("Raw OPC-UA Server");
  const [rootName, setRootName] = useState("");
  const [port, setPort] = useState<string>("");
  const [autostart, setAutostart] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const create = async () => {
    if (!name.trim()) {
      setErr("Give the source a name");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await api.plcBlank({
        name: name.trim(),
        rootName: rootName.trim() || undefined,
        port: port ? Number(port) : undefined,
        autostart,
      });
      if (res.ok && res.instance) onCreated(res.instance);
      else setErr(res.msg || "Could not create the source");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="rise-in w-full max-w-md rounded-xl border border-border bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Cpu size={16} className="text-warn" />
          <h3 className="text-sm font-semibold text-fg">New raw OPC-UA server</h3>
          <button onClick={onClose} aria-label="Close" className="ml-auto text-fg-faint hover:text-fg">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3 p-4">
          <p className="text-[12px] text-fg-muted">
            An empty OPC-UA server, published to nothing. Fill it with asset bundles at whatever rawness you
            like, then point a gateway or protocol converter at it and let someone model the UNS themselves.
          </p>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wide text-fg-faint">Name</span>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wide text-fg-faint">
              Root / channel name (optional)
            </span>
            <input
              className={inputCls}
              value={rootName}
              placeholder="defaults to the name"
              onChange={(e) => setRootName(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wide text-fg-faint">
              OPC-UA port (optional)
            </span>
            <input
              className={inputCls}
              value={port}
              placeholder="next free port"
              inputMode="numeric"
              onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))}
            />
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              checked={autostart}
              onChange={(e) => setAutostart(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent)]"
            />
            Start it with the studio
          </label>
          {err && <p className="text-[12px] text-err">{err}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={create} disabled={busy}>
            {busy ? "Creating…" : "Create"}
          </Button>
        </div>
      </div>
    </div>
  );
}
