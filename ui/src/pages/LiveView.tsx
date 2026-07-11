import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import mqtt, { type MqttClient } from "mqtt";
import { ChevronRight, Diamond, Plug, PlugZap, Radio, Search, Trash2 } from "lucide-react";
import { Page, Field, Button, inputCls, cx } from "../components/ui";

interface TNode {
  children: Record<string, TNode>;
  value: string | null;
  ts: number;
  count: number;
  isLeaf: boolean;
  topic?: string;
}

interface Cfg {
  host: string;
  port: string;
  path: string;
  topic: string;
  user: string;
  pass: string;
}

const SETTINGS_KEY = "uns-live-settings";

function autoDetect(): Cfg {
  const loc = window.location;
  return {
    host: loc.hostname,
    port: loc.port || (loc.protocol === "https:" ? "443" : "80"),
    path: "/mqtt-ws",
    topic: "#",
    user: "",
    pass: "",
  };
}

function loadCfg(): Cfg {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...autoDetect(), ...JSON.parse(raw), pass: "" };
  } catch {
    /* ignore */
  }
  return autoDetect();
}

function countLeaves(node: Record<string, TNode>): number {
  return Object.values(node).reduce((s, n) => s + (n.isLeaf ? 1 : 0) + countLeaves(n.children), 0);
}

function displayValue(raw: string): { text: string; kind: "num" | "str" | "bool" } {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      const v = (parsed.value ?? parsed.v ?? Object.values(parsed)[0]) as unknown;
      const kind = typeof (parsed.value ?? v) === "boolean" ? "bool" : typeof (parsed.value ?? v) === "string" ? "str" : "num";
      return { text: v !== undefined ? String(v) : "{…}", kind };
    }
    return { text: String(parsed), kind: typeof parsed === "boolean" ? "bool" : typeof parsed === "string" ? "str" : "num" };
  } catch {
    return { text: raw.length > 30 ? raw.slice(0, 30) + "…" : raw, kind: "str" };
  }
}

function ageStr(ts: number): string {
  const a = Math.floor((Date.now() - ts) / 1000);
  return a < 60 ? `${a}s` : `${Math.floor(a / 60)}m`;
}

export function LiveView() {
  const [cfg, setCfg] = useState<Cfg>(loadCfg);
  const [status, setStatus] = useState<{ tone: "" | "ok" | "warn" | "err"; text: string }>({
    tone: "",
    text: "Disconnected",
  });
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const clientRef = useRef<MqttClient | null>(null);
  const treeRef = useRef<Record<string, TNode>>({});
  const statsRef = useRef({ msgs: 0, rateCounter: 0 });
  const [stats, setStats] = useState({ topics: 0, msgs: 0, rate: 0, last: "" });
  const [, forceRender] = useReducer((n) => n + 1, 0);

  // Persist config (never the password).
  useEffect(() => {
    const { pass, ...rest } = cfg;
    void pass;
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(rest));
  }, [cfg]);

  // Throttled render + rate/stat tick — the broker can push thousands of msgs/s,
  // so we mutate a ref on each message and flush to the DOM at a fixed cadence.
  useEffect(() => {
    const render = setInterval(() => forceRender(), 200);
    const rate = setInterval(() => {
      setStats((s) => ({ ...s, rate: statsRef.current.rateCounter, msgs: statsRef.current.msgs, topics: countLeaves(treeRef.current) }));
      statsRef.current.rateCounter = 0;
    }, 1000);
    return () => {
      clearInterval(render);
      clearInterval(rate);
    };
  }, []);

  const onMessage = useCallback((topic: string, payload: string) => {
    const parts = topic.split("/");
    let node = treeRef.current;
    parts.forEach((part, i) => {
      if (!node[part]) node[part] = { children: {}, value: null, ts: 0, count: 0, isLeaf: false };
      if (i === parts.length - 1) {
        node[part].isLeaf = true;
        node[part].value = payload;
        node[part].ts = Date.now();
        node[part].count += 1;
        node[part].topic = topic;
      }
      node = node[part].children;
    });
    statsRef.current.msgs += 1;
    statsRef.current.rateCounter += 1;
    setStats((s) => (s.last === parts[parts.length - 1] ? s : { ...s, last: parts[parts.length - 1] }));
  }, []);

  const connect = () => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${cfg.host}:${cfg.port}${cfg.path || "/mqtt-ws"}`;
    setStatus({ tone: "warn", text: "Connecting…" });
    const opts: mqtt.IClientOptions = {
      clientId: "uns-live-" + Math.random().toString(16).slice(2, 10),
      clean: true,
      reconnectPeriod: 3000,
    };
    if (cfg.user) {
      opts.username = cfg.user;
      opts.password = cfg.pass;
    }
    const client = mqtt.connect(url, opts);
    clientRef.current = client;

    client.on("connect", () => {
      setStatus({ tone: "ok", text: `Connected — ${cfg.host}:${cfg.port}` });
      setConnected(true);
      client.subscribe(cfg.topic || "#", { qos: 0 });
    });
    client.on("message", (t, m) => onMessage(t, m.toString()));
    client.on("error", (e) => setStatus({ tone: "err", text: "Error: " + e.message }));
    client.on("close", () => {
      setStatus({ tone: "err", text: "Disconnected" });
      setConnected(false);
    });
  };

  const disconnect = () => {
    clientRef.current?.end(true);
    clientRef.current = null;
    setConnected(false);
    setStatus({ tone: "", text: "Disconnected" });
  };

  useEffect(() => {
    return () => {
      clientRef.current?.end(true);
    };
  }, []);

  const clearTree = () => {
    treeRef.current = {};
    statsRef.current = { msgs: 0, rateCounter: 0 };
    setStats({ topics: 0, msgs: 0, rate: 0, last: "" });
    setSelected(null);
    setExpanded(new Set());
  };

  const toggle = (path: string) =>
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(path) ? n.delete(path) : n.add(path);
      return n;
    });

  const detail = useMemo(() => {
    if (!selected) return null;
    let cursor = treeRef.current;
    let found: TNode | null = null;
    for (const p of selected.split("/")) {
      if (!cursor[p]) return null;
      found = cursor[p];
      cursor = found.children;
    }
    if (!found) return null;
    let pretty = found.value || "";
    try {
      pretty = JSON.stringify(JSON.parse(found.value || ""), null, 2);
    } catch {
      /* keep raw */
    }
    return { pretty, ts: found.ts, count: found.count, depth: selected.split("/").length };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, stats]);

  const statusDot =
    status.tone === "ok" ? "bg-ok" : status.tone === "warn" ? "bg-warn" : status.tone === "err" ? "bg-err" : "bg-fg-faint";

  return (
    <Page
      title="Live UNS View"
      subtitle="Subscribe to the broker and inspect the live published topic tree."
      actions={
        <div className="flex items-center gap-2 text-[12px]">
          <span className={cx("h-2 w-2 rounded-full", statusDot)} />
          <span className="text-fg-muted">{status.text}</span>
        </div>
      }
    >
      <div className="grid grid-cols-4 gap-3">
        <Stat label="Topics" value={stats.topics} />
        <Stat label="Messages" value={stats.msgs} />
        <Stat label="Msgs/sec" value={stats.rate} />
        <Stat label="Last topic" value={stats.last || "—"} mono />
      </div>

      <div className="flex gap-4">
        {/* config panel */}
        <div className="w-64 shrink-0 space-y-3 rounded-xl border border-border bg-surface p-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Host">
              <input className={inputCls} value={cfg.host} onChange={(e) => setCfg({ ...cfg, host: e.target.value })} />
            </Field>
            <Field label="Port">
              <input className={inputCls} value={cfg.port} onChange={(e) => setCfg({ ...cfg, port: e.target.value })} />
            </Field>
          </div>
          <Field label="WS path">
            <input className={inputCls} value={cfg.path} onChange={(e) => setCfg({ ...cfg, path: e.target.value })} />
          </Field>
          <Field label="Topic filter">
            <input className={inputCls} value={cfg.topic} onChange={(e) => setCfg({ ...cfg, topic: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="User">
              <input className={inputCls} value={cfg.user} onChange={(e) => setCfg({ ...cfg, user: e.target.value })} />
            </Field>
            <Field label="Password">
              <input className={inputCls} type="password" value={cfg.pass} onChange={(e) => setCfg({ ...cfg, pass: e.target.value })} />
            </Field>
          </div>
          {connected ? (
            <Button variant="ghost" onClick={disconnect}>
              <span className="flex items-center gap-1.5"><PlugZap size={14} /> Disconnect</span>
            </Button>
          ) : (
            <Button onClick={connect}>
              <span className="flex items-center gap-1.5"><Plug size={14} /> Connect</span>
            </Button>
          )}
          <button
            onClick={() => setCfg(autoDetect())}
            className="w-full text-[11px] text-fg-faint hover:text-accent"
          >
            Reset to this host's defaults
          </button>
        </div>

        {/* tree */}
        <div className="flex min-h-[460px] flex-1 flex-col rounded-xl border border-border bg-surface">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search size={14} className="text-fg-faint" />
            <input
              className="flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-faint"
              placeholder="Filter topics / values…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <span className="text-[11px] text-fg-muted">{stats.topics} leaves</span>
            <button onClick={clearTree} title="Clear" className="text-fg-faint hover:text-err">
              <Trash2 size={14} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto py-1 font-mono text-[12px]">
            {Object.keys(treeRef.current).length === 0 ? (
              <div className="grid h-full place-items-center text-center text-fg-muted">
                <div>
                  <Radio size={20} className="mx-auto text-fg-faint" />
                  <p className="mt-2 font-sans">Connect to see live topics stream in.</p>
                </div>
              </div>
            ) : (
              Object.entries(treeRef.current).map(([k, n]) => (
                <TreeRow
                  key={k}
                  name={k}
                  node={n}
                  depth={0}
                  path={k}
                  filter={filter.toLowerCase()}
                  expanded={expanded}
                  selected={selected}
                  onToggle={toggle}
                  onSelect={setSelected}
                />
              ))
            )}
          </div>
        </div>

        {/* detail */}
        <div className="w-72 shrink-0 rounded-xl border border-border bg-surface">
          <div className="border-b border-border px-3 py-2 text-sm font-semibold text-fg">Detail</div>
          {!detail || !selected ? (
            <p className="px-3 py-6 text-center text-[12px] text-fg-muted">Click any leaf node to inspect its value.</p>
          ) : (
            <div className="p-3">
              <div className="mb-2 break-all font-mono text-[11px] text-accent">{selected}</div>
              <pre className="max-h-64 overflow-auto rounded-lg bg-bg p-2 font-mono text-[12px] text-fg">{detail.pretty}</pre>
              <dl className="mt-3 space-y-1 text-[12px]">
                <Row k="Last update" v={`${ageStr(detail.ts)} ago`} />
                <Row k="Messages" v={detail.count} />
                <Row k="Topic depth" v={detail.depth} />
              </dl>
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}

function matchesFilter(path: string, node: TNode, q: string): boolean {
  if (!q) return true;
  if (path.toLowerCase().includes(q)) return true;
  if (node.isLeaf && node.value && node.value.toLowerCase().includes(q)) return true;
  return Object.entries(node.children).some(([k, n]) => matchesFilter(path + "/" + k, n, q));
}

function TreeRow({
  name,
  node,
  depth,
  path,
  filter,
  expanded,
  selected,
  onToggle,
  onSelect,
}: {
  name: string;
  node: TNode;
  depth: number;
  path: string;
  filter: string;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (p: string) => void;
  onSelect: (p: string) => void;
}) {
  if (filter && !matchesFilter(path, node, filter)) return null;
  const hasChildren = Object.keys(node.children).length > 0;
  const isExp = expanded.has(path) || (!!filter && hasChildren);
  const val = node.isLeaf && node.value !== null ? displayValue(node.value) : null;
  const valColor = val?.kind === "str" ? "text-accent" : val?.kind === "bool" ? "text-warn" : "text-ok";

  return (
    <div>
      <div
        onClick={() => (node.isLeaf ? onSelect(path) : onToggle(path))}
        className={cx(
          "flex cursor-pointer items-center gap-1 py-[3px] pr-2 hover:bg-surface-2",
          selected === path && "bg-accent-soft",
        )}
        style={{ paddingLeft: depth * 12 + 6 }}
      >
        {hasChildren ? (
          <ChevronRight
            size={12}
            className={cx("shrink-0 text-fg-faint transition-transform", isExp && "rotate-90")}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(path);
            }}
          />
        ) : (
          <Diamond size={9} className="ml-0.5 mr-0.5 shrink-0 text-accent" />
        )}
        <span className={cx("truncate", node.isLeaf ? "text-fg" : "text-fg-muted")}>{name}</span>
        {val && <span className={cx("ml-2 truncate", valColor)}>{val.text}</span>}
        {node.isLeaf && node.ts > 0 && <span className="ml-auto shrink-0 text-fg-faint">{ageStr(node.ts)}</span>}
      </div>
      {isExp &&
        hasChildren &&
        Object.entries(node.children).map(([k, n]) => (
          <TreeRow
            key={k}
            name={k}
            node={n}
            depth={depth + 1}
            path={path + "/" + k}
            filter={filter}
            expanded={expanded}
            selected={selected}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

function Stat({ label, value, mono }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2">
      <div className={cx("text-lg font-semibold tabular-nums text-fg", mono && "truncate font-mono text-sm")}>{value}</div>
      <div className="text-[11px] text-fg-muted">{label}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-fg-muted">{k}</dt>
      <dd className="font-medium text-fg">{v}</dd>
    </div>
  );
}
