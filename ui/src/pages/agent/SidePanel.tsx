import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, History, Loader2, RotateCcw, ScrollText, Waypoints } from "lucide-react";
import { api, type PolicyReport, type PolicyViolation, type TopicPolicy } from "../../api";
import { cx, inputCls } from "../../components/ui";

type Tab = "policy" | "topics" | "history";

const TABS: Array<{ id: Tab; label: string; icon: typeof ScrollText }> = [
  { id: "policy", label: "Policy", icon: ScrollText },
  { id: "topics", label: "Topics", icon: Waypoints },
  { id: "history", label: "Undo", icon: History },
];

/** The context the chat needs beside it: the rulebook the agent is modelling
 *  against, the topics that rulebook currently produces, and the way back. */
export function SidePanel() {
  const [tab, setTab] = useState<Tab>("policy");
  return (
    <aside className="flex w-[380px] shrink-0 flex-col border-l border-border bg-surface">
      <div className="flex gap-1 border-b border-border p-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cx(
              "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[12px] font-medium transition-tokens",
              tab === id ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-surface-2",
            )}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "policy" && <PolicyTab />}
        {tab === "topics" && <TopicsTab />}
        {tab === "history" && <HistoryTab />}
      </div>
    </aside>
  );
}

// ── policy ──────────────────────────────────────────────────────────────────

function PolicyTab() {
  const qc = useQueryClient();
  const policy = useQuery({ queryKey: ["policy"], queryFn: api.agentPolicy });
  const check = useQuery({
    queryKey: ["policy-check"],
    queryFn: () => api.agentPolicyCheck(25),
  });

  const [form, setForm] = useState<TopicPolicy | null>(null);
  const seeded = useRef<string | null>(null);
  const snapshot = policy.data ? JSON.stringify(policy.data) : null;

  // Re-seed whenever the server's copy changes — the agent edits this policy
  // too (policy_set), so the panel must follow it, not fight it.
  useEffect(() => {
    if (snapshot && snapshot !== seeded.current) {
      seeded.current = snapshot;
      setForm(JSON.parse(snapshot) as TopicPolicy);
    }
  }, [snapshot]);

  const save = useMutation({
    mutationFn: api.agentPolicySave,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy"] });
      qc.invalidateQueries({ queryKey: ["policy-check"] });
    },
  });

  if (!form) return <Loading />;
  const set = <K extends keyof TopicPolicy>(k: K, v: TopicPolicy[K]) =>
    setForm({ ...form, [k]: v });

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] leading-relaxed text-fg-muted">
        The rulebook the agent models against. It is injected into the agent's prompt every turn,
        and <code className="font-mono">policy_check</code> grades the model against it.
      </p>

      <Row label="Name">
        <input
          className={inputCls}
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
        />
      </Row>

      <div className="grid grid-cols-2 gap-2">
        <Row label="Topic prefix">
          <input
            className={inputCls}
            value={form.prefix}
            placeholder="uns"
            onChange={(e) => set("prefix", e.target.value)}
          />
        </Row>
        <Row label="Separator">
          <select
            className={inputCls}
            value={form.separator}
            onChange={(e) => set("separator", e.target.value)}
          >
            <option value="/">/ (MQTT)</option>
            <option value=".">. (NATS)</option>
          </select>
        </Row>
        <Row label="Node names">
          <CaseSelect value={form.caseRule} onChange={(v) => set("caseRule", v)} />
        </Row>
        <Row label="Tag names">
          <CaseSelect
            value={form.tag?.caseRule ?? ""}
            onChange={(v) => set("tag", { ...form.tag, caseRule: v })}
          />
        </Row>
      </div>

      <Row label="Allowed tag qualifiers" hint="Comma-separated. Empty means unconstrained.">
        <input
          className={inputCls}
          value={(form.tag?.qualifiers ?? []).join(", ")}
          placeholder="data, command, state"
          onChange={(e) =>
            set("tag", { ...form.tag, qualifiers: splitList(e.target.value) })
          }
        />
      </Row>

      <Row label="Levels" hint="Tick the ISA-95 levels this namespace uses; required ones must exist.">
        <div className="flex flex-col gap-1 rounded-lg border border-border bg-bg p-2">
          {form.levels.map((lv, i) => (
            <label key={lv.type} className="flex items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={!!lv.required}
                onChange={(e) => {
                  const next = [...form.levels];
                  next[i] = { ...lv, required: e.target.checked };
                  set("levels", next);
                }}
              />
              <span className="font-mono text-fg">{lv.type}</span>
              <span className="ml-auto text-[10px] text-fg-faint">
                {lv.required ? "required" : "optional"}
              </span>
            </label>
          ))}
        </div>
      </Row>

      <Row
        label="Policy notes"
        hint="Paste the parts of your policy document a regex can't check — the agent is told to treat these as binding."
      >
        <textarea
          rows={5}
          className="w-full rounded-lg border border-border bg-bg p-2 text-[12px] text-fg outline-none focus:border-accent"
          value={form.notes}
          placeholder="Sites are ISO-3166 country code, dash, town. No vendor names in topics."
          onChange={(e) => set("notes", e.target.value)}
        />
      </Row>

      <button
        onClick={() => save.mutate(form)}
        disabled={save.isPending}
        className="flex items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-[13px] font-medium text-accent-fg hover:bg-accent-hover disabled:opacity-50"
      >
        {save.isPending ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
        Save policy
      </button>

      <ComplianceReport report={check.data} loading={check.isLoading} />
    </div>
  );
}

function ComplianceReport({
  report,
  loading,
}: {
  report: PolicyReport | undefined;
  loading: boolean;
}) {
  if (loading) return <Loading />;
  if (!report) return null;
  return (
    <div className="rounded-lg border border-border">
      <div
        className={cx(
          "flex items-center gap-2 rounded-t-lg px-2.5 py-2 text-[12px] font-medium",
          report.ok ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn",
        )}
      >
        {report.ok ? <Check size={13} /> : <ScrollText size={13} />}
        {report.ok
          ? `Compliant — ${report.counts.topics} topics`
          : `${report.counts.violations} violation${report.counts.violations === 1 ? "" : "s"}`}
      </div>
      {!report.ok && (
        <ul className="max-h-64 divide-y divide-border overflow-y-auto">
          {report.violations.map((v: PolicyViolation, i: number) => (
            <li key={i} className="px-2.5 py-1.5">
              <div className="truncate font-mono text-[10px] text-fg-faint" title={v.path}>
                {v.path}
              </div>
              <div className="text-[11px] text-fg">{v.message}</div>
              {v.fix && <div className="text-[10px] text-fg-muted">→ {v.fix}</div>}
            </li>
          ))}
          {report.truncated && (
            <li className="px-2.5 py-1.5 text-[10px] text-fg-faint">
              …and {report.counts.violations - report.reported} more. Ask the agent to fix them.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

// ── topics ──────────────────────────────────────────────────────────────────

function TopicsTab() {
  const [filter, setFilter] = useState("");
  const topics = useQuery({
    queryKey: ["agent-topics", filter],
    queryFn: () => api.agentTopics(filter, 150),
  });

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] leading-relaxed text-fg-muted">
        Exactly what the bridge would publish for the current model — the same walk, not an
        approximation.
      </p>
      <input
        className={inputCls}
        placeholder="Filter topics…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {topics.isLoading ? (
        <Loading />
      ) : (
        <TopicList
          total={topics.data?.total ?? 0}
          rows={topics.data?.topics ?? []}
          separator={topics.data?.separator ?? "/"}
        />
      )}
    </div>
  );
}

/** Topics in a UNS share a deep prefix — often 60 characters of enterprise and
 *  site before anything varies. Truncating each row leaves a column of
 *  identical strings, so the shared head is lifted out and shown once and each
 *  row keeps only the part that actually distinguishes it. */
function TopicList({
  total,
  rows,
  separator,
}: {
  total: number;
  rows: Array<{ topic: string; unit: string; dataType: string; tag: string }>;
  separator: string;
}) {
  const shared = commonPrefix(rows.map((r) => r.topic), separator);
  return (
    <>
      <div className="text-[11px] text-fg-muted">
        {total} topic{total === 1 ? "" : "s"}
        {total > rows.length && ` · showing ${rows.length}`}
      </div>
      {shared && (
        <div className="rounded-lg border border-border bg-bg px-2 py-1.5">
          <div className="text-[10px] font-medium text-fg-faint">Common prefix</div>
          <div className="break-all font-mono text-[10.5px] text-fg-muted">
            {shared}
            {separator}
          </div>
        </div>
      )}
      <ul className="flex flex-col gap-0.5 font-mono text-[10.5px] leading-relaxed">
        {rows.map((t) => (
          <li
            key={t.topic}
            className="break-all rounded px-1.5 py-1 text-fg hover:bg-surface-2"
            title={`${t.topic}  (${t.dataType}${t.unit ? ` ${t.unit}` : ""})`}
          >
            {shared ? t.topic.slice(shared.length + separator.length) : t.topic}
            {t.unit && <span className="ml-1 text-fg-faint">{t.unit}</span>}
          </li>
        ))}
      </ul>
    </>
  );
}

/** Longest whole-segment prefix shared by every topic. Whole segments only —
 *  half a level name is not a prefix anyone wants to read. */
function commonPrefix(topics: string[], separator: string): string {
  if (topics.length < 2) return "";
  const split = topics.map((t) => t.split(separator));
  const shortest = Math.min(...split.map((p) => p.length));
  const shared: string[] = [];
  for (let i = 0; i < shortest - 1; i++) {
    const part = split[0][i];
    if (!split.every((p) => p[i] === part)) break;
    shared.push(part);
  }
  return shared.join(separator);
}

// ── undo history ────────────────────────────────────────────────────────────

function HistoryTab() {
  const qc = useQueryClient();
  const snapshots = useQuery({ queryKey: ["agent-snapshots"], queryFn: api.agentSnapshots });
  const revert = useMutation({
    mutationFn: api.agentRevert,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-snapshots"] });
      qc.invalidateQueries({ queryKey: ["policy-check"] });
      qc.invalidateQueries({ queryKey: ["agent-topics"] });
      qc.invalidateQueries({ queryKey: ["uns"] });
      qc.invalidateQueries({ queryKey: ["graph"] });
    },
  });

  const items = snapshots.data?.snapshots ?? [];
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] leading-relaxed text-fg-muted">
        A snapshot is taken before every agent edit. Reverting is itself snapshotted, so you can
        always come back.
      </p>
      {snapshots.isLoading && <Loading />}
      {!snapshots.isLoading && items.length === 0 && (
        <p className="text-[11px] text-fg-faint">The agent hasn't changed anything yet.</p>
      )}
      {items.map((s) => (
        <div key={s.id} className="rounded-lg border border-border px-2.5 py-2">
          <div className="text-[12px] text-fg">{s.label || "model change"}</div>
          <div className="mt-0.5 flex items-center gap-2 text-[10px] text-fg-faint">
            <span>{s.takenAt.replace("T", " ").replace("Z", " UTC")}</span>
            <span>·</span>
            <span>{s.nodes} nodes</span>
            <button
              onClick={() => revert.mutate(s.id)}
              disabled={revert.isPending}
              className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
            >
              <RotateCcw size={10} />
              Restore
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── shared bits ─────────────────────────────────────────────────────────────

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-fg-muted">{label}</span>
      {children}
      {hint && <span className="text-[10px] leading-relaxed text-fg-faint">{hint}</span>}
    </label>
  );
}

function CaseSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="kebab">lower-kebab</option>
      <option value="snake">snake_case</option>
      <option value="lower">lowercase</option>
      <option value="upper">UPPER_CASE</option>
      <option value="pascal">PascalCase</option>
      <option value="any">any</option>
    </select>
  );
}

function splitList(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function Loading() {
  return (
    <div className="flex items-center gap-2 py-3 text-[12px] text-fg-muted">
      <Loader2 size={13} className="animate-spin" /> Loading…
    </div>
  );
}
