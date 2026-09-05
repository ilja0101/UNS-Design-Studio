import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, Server, Cable, Check, Loader2 } from "lucide-react";
import { api, type ShiftConfig, type ServerConfig, type BridgeConfig } from "../api";
import { Page, Card, Field, Button, Toggle, inputCls, cx } from "../components/ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Parse a shift day spec ("Mon-Fri", "Sat,Sun", "daily") into a selected set of
// weekday indices (Mon=0), mirroring the backend's shift.parse_days.
function parseDays(spec: string): Set<number> {
  const s = (spec || "Mon-Fri").trim().toLowerCase();
  if (["daily", "all", "everyday", "7", "*"].includes(s)) return new Set([0, 1, 2, 3, 4, 5, 6]);
  const idx = (n: string) => DAYS.findIndex((d) => d.toLowerCase() === n.slice(0, 3));
  const out = new Set<number>();
  for (const tok of s.replace(/\s/g, "").split(",")) {
    if (!tok) continue;
    if (tok.includes("-")) {
      const [a, b] = tok.split("-");
      let ia = idx(a);
      const ib = idx(b);
      if (ia < 0 || ib < 0) continue;
      while (true) {
        out.add(ia);
        if (ia === ib) break;
        ia = (ia + 1) % 7;
      }
    } else {
      const i = idx(tok);
      if (i >= 0) out.add(i);
    }
  }
  return out;
}

const serializeDays = (set: Set<number>) =>
  set.size === 7
    ? "daily"
    : DAYS.filter((_, i) => set.has(i)).join(",") || "Mon-Fri";

/** Local edit state seeded from the server, re-seeded when the server changes.
 *
 *  The previous `if (data && !form) setForm(data)` seeded once per mount and
 *  never again. Combined with a save that did not invalidate its query, that
 *  meant: save → cache still holds the pre-save config → navigate away → the
 *  card remounts and seeds from that stale cache → the edit looks reverted, and
 *  saving again is the only way to make it stick. Comparing snapshots re-seeds
 *  after a save without clobbering edits on a refetch that changed nothing.
 */
function useServerForm<T>(data: T | undefined) {
  const [form, setForm] = useState<T | null>(null);
  const seeded = useRef<string | null>(null);
  const snapshot = data === undefined ? null : JSON.stringify(data);

  useEffect(() => {
    if (snapshot !== null && snapshot !== seeded.current) {
      seeded.current = snapshot;
      setForm(JSON.parse(snapshot) as T);
    }
  }, [snapshot]);

  return [form, setForm] as const;
}

function SavedTick({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span className="flex items-center gap-1 text-[12px] font-medium text-ok">
      <Check size={13} /> Saved
    </span>
  );
}

function ShiftCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["shift"], queryFn: api.shift });
  // api.shift returns live status too (running/total/state), which changes on
  // its own — seed only the editable fields so status churn cannot re-seed.
  const [form, setForm] = useServerForm<ShiftConfig>(
    data && { enabled: data.enabled, start: data.start, end: data.end, days: data.days, tz: data.tz },
  );
  const [days, setDays] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (form) setDays(parseDays(form.days));
  }, [form?.days]);

  const save = useMutation({
    mutationFn: () => api.shiftSave({ ...form!, days: serializeDays(days) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shift"] }),
  });

  if (!form) return <Card title="Production shift hours" icon={<Clock size={16} />}>Loading…</Card>;

  return (
    <Card
      title="Production shift hours"
      desc="Factories run only during shift; off-hours the simulation pauses automatically to save cost."
      icon={<Clock size={16} />}
      footer={
        <>
          <SavedTick show={save.isSuccess && !save.isPending} />
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save schedule"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium text-fg">Shift schedule enabled</div>
            <div className="text-xs text-fg-muted">
              {data && (
                <>Currently {data.running}/{data.total} plants running · {data.state}</>
              )}
            </div>
          </div>
          <Toggle on={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Start">
            <input
              type="time"
              className={inputCls}
              value={form.start}
              onChange={(e) => setForm({ ...form, start: e.target.value })}
            />
          </Field>
          <Field label="End">
            <input
              type="time"
              className={inputCls}
              value={form.end}
              onChange={(e) => setForm({ ...form, end: e.target.value })}
            />
          </Field>
        </div>

        <Field label="Production days">
          <div className="flex flex-wrap gap-1.5">
            {DAYS.map((d, i) => (
              <button
                key={d}
                type="button"
                onClick={() => {
                  const next = new Set(days);
                  next.has(i) ? next.delete(i) : next.add(i);
                  setDays(next);
                }}
                className={cx(
                  "rounded-lg border px-2.5 py-1 text-[12px] font-medium transition-tokens",
                  days.has(i)
                    ? "border-accent bg-accent text-accent-fg"
                    : "border-border bg-surface text-fg-muted hover:border-accent",
                )}
              >
                {d}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Timezone" hint="IANA name, e.g. Europe/Amsterdam. Falls back to UTC if unavailable.">
          <input
            className={inputCls}
            value={form.tz}
            onChange={(e) => setForm({ ...form, tz: e.target.value })}
          />
        </Field>
      </div>
    </Card>
  );
}

function ServerCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["server-config"], queryFn: api.serverConfig });
  const [form, setForm] = useServerForm<ServerConfig>(data);

  const save = useMutation({
    mutationFn: () => api.serverConfigSave(form!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["server-config"] }),
  });
  if (!form) return <Card title="OPC-UA server" icon={<Server size={16} />}>Loading…</Card>;

  const set = (k: keyof ServerConfig, v: string) =>
    setForm({ ...form, [k]: k.includes("port") ? Number(v) : v });

  return (
    <Card
      title="OPC-UA server"
      desc="Endpoint the simulated factory address space is served on. Restart the server to apply."
      icon={<Server size={16} />}
      footer={
        <>
          <SavedTick show={save.isSuccess && !save.isPending} />
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save server config"}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Bind IP" hint="0.0.0.0 listens on all interfaces">
          <input className={inputCls} value={form.opc_bind_ip} onChange={(e) => set("opc_bind_ip", e.target.value)} />
        </Field>
        <Field label="OPC-UA port">
          <input className={inputCls} type="number" value={form.opc_port} onChange={(e) => set("opc_port", e.target.value)} />
        </Field>
        <Field label="Client host" hint="Advertised endpoint host for clients">
          <input className={inputCls} value={form.opc_client_host} onChange={(e) => set("opc_client_host", e.target.value)} />
        </Field>
        <Field label="Host IP">
          <input className={inputCls} value={form.host_ip} onChange={(e) => set("host_ip", e.target.value)} />
        </Field>
      </div>
    </Card>
  );
}

function BridgeCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["bridge-config"], queryFn: api.bridgeConfig });
  const [form, setForm] = useServerForm<BridgeConfig>(data);
  const [password, setPassword] = useState("");

  const save = useMutation({
    mutationFn: () => api.bridgeConfigSave(password ? { ...form!, password } : form!),
    onSuccess: () => {
      setPassword("");   // it is stored now; keeping it would re-send on every save
      qc.invalidateQueries({ queryKey: ["bridge-config"] });
    },
  });
  if (!form) return <Card title="MQTT / NATS bridge" icon={<Cable size={16} />}>Loading…</Card>;

  // AMIX governed mode: the broker + topic scope are platform-owned and come
  // read-only ("Managed by AMIX"); the app rejects a save that changes them.
  const managed = ((data as { managed_fields?: string[] }).managed_fields) ?? [];
  const isManaged = (k: string) => managed.includes(k);
  const managedHint = "Managed by AMIX";

  const set = (k: keyof BridgeConfig, v: string) =>
    setForm({ ...form, [k]: k === "broker_port" || k === "interval" ? Number(v) : v });

  return (
    <Card
      title="MQTT / NATS bridge"
      desc="Broker the live UNS is published to. Changes apply on the bridge's next restart."
      icon={<Cable size={16} />}
      footer={
        <>
          <SavedTick show={save.isSuccess && !save.isPending} />
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save bridge config"}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Protocol">
          <select className={inputCls} value={form.protocol} onChange={(e) => set("protocol", e.target.value)}>
            <option value="mqtt">MQTT</option>
            <option value="nats">NATS</option>
          </select>
        </Field>
        <Field label="Publish interval (s)">
          <input className={inputCls} type="number" step="0.1" value={form.interval} onChange={(e) => set("interval", e.target.value)} />
        </Field>
        <Field label="Broker host" hint={isManaged("broker_host") ? managedHint : undefined}>
          <input className={inputCls} value={form.broker_host} disabled={isManaged("broker_host")}
                 onChange={(e) => set("broker_host", e.target.value)} />
        </Field>
        <Field label="Broker port" hint={isManaged("broker_port") ? managedHint : undefined}>
          <input className={inputCls} type="number" value={form.broker_port} disabled={isManaged("broker_port")}
                 onChange={(e) => set("broker_port", e.target.value)} />
        </Field>
        <Field label="Topic prefix" hint={isManaged("topic_prefix") ? managedHint : "Root of the published UNS topic tree"}>
          <input className={inputCls} value={form.topic_prefix} disabled={isManaged("topic_prefix")}
                 onChange={(e) => set("topic_prefix", e.target.value)} />
        </Field>
        <Field label="Username">
          <input className={inputCls} value={form.username} onChange={(e) => set("username", e.target.value)} />
        </Field>
        <Field label="Password" hint="Leave blank to keep the stored password">
          <input className={inputCls} type="password" value={password} placeholder="••••••••" onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </div>
    </Card>
  );
}

export function Settings() {
  return (
    <Page title="Settings" subtitle="Simulator, OPC-UA server, broker bridge and production shift hours.">
      <ShiftCard />
      <ServerCard />
      <BridgeCard />
    </Page>
  );
}
