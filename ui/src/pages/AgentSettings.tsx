import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Copy, Loader2, Plug, RefreshCw } from "lucide-react";
import { api, type AgentSettings as Settings } from "../api";
import { Button, Card, Field, Toggle, cx, inputCls } from "../components/ui";

/** Editable slice of the agent settings. The API key is write-only: the server
 *  never sends it back, and an empty string on save means "leave it alone". */
type Form = Pick<
  Settings,
  "route" | "meshProtocol" | "meshHost" | "meshPort" | "meshUsername" | "meshCreds" | "meshAppId" |
  "meshModel" | "meshPerson" | "meshPurpose" | "meshTimeout" |
  "endpoint" | "model" | "maxTokens" | "maxSteps" | "allowWrites" | "systemPromptExtra" |
  "mcpEnabled" | "mcpAllowWrites"
> & { apiKey: string; meshPassword: string };

function toForm(s: Settings): Form {
  return {
    route: s.route ?? "direct",
    meshProtocol: s.meshProtocol ?? "",
    meshHost: s.meshHost ?? "",
    meshPort: s.meshPort ?? 0,
    meshUsername: s.meshUsername ?? "",
    meshCreds: s.meshCreds ?? "",
    meshAppId: s.meshAppId ?? "uns-design-studio",
    meshModel: s.meshModel ?? "",
    meshPerson: s.meshPerson ?? "",
    meshPurpose: s.meshPurpose ?? "",
    meshTimeout: s.meshTimeout ?? 120,
    meshPassword: "",
    endpoint: s.endpoint,
    model: s.model,
    maxTokens: s.maxTokens,
    maxSteps: s.maxSteps,
    allowWrites: s.allowWrites,
    systemPromptExtra: s.systemPromptExtra,
    mcpEnabled: s.mcpEnabled,
    mcpAllowWrites: s.mcpAllowWrites,
    apiKey: "",
  };
}

export function AgentCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["agent-settings"], queryFn: api.agentSettings });
  const [form, setForm] = useState<Form | null>(null);
  const seeded = useRef<string | null>(null);
  const snapshot = data ? JSON.stringify(toForm(data)) : null;

  useEffect(() => {
    if (snapshot && snapshot !== seeded.current) {
      seeded.current = snapshot;
      setForm(JSON.parse(snapshot) as Form);
    }
  }, [snapshot]);

  const save = useMutation({
    mutationFn: (patch: Partial<Form>) => api.agentSettingsSave(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-settings"] }),
  });

  if (!form || !data)
    return (
      <Card title="Agent" icon={<Bot size={16} />}>
        Loading…
      </Card>
    );

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });
  const envLocked = data.envManaged ?? {};

  return (
    <Card
      title="Agent"
      desc="The built-in modelling assistant. Reach a model the way the other applications do — over this app's own backbone to the Model Gateway — or directly, with a key this app holds."
      icon={<Bot size={16} />}
      footer={
        <>
          {save.isSuccess && !save.isPending && (
            <span className="flex items-center gap-1 text-[12px] font-medium text-ok">
              <Check size={13} /> Saved
            </span>
          )}
          <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save agent settings"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {/* Two doors, same as pkg/appshell gives every application on the
            platform. The mesh is the default there and the only route from the
            OT tier; the direct endpoint is for a demo box with a key. */}
        <div className="grid gap-2 sm:grid-cols-2">
          <RouteChoice
            active={form.route === "mesh"}
            title="Model Gateway over the mesh"
            body="Ask the platform's gateway over this app's own backbone. No key here, no route needed — the gateway names this app, decides what it may reach, and records what it spends. Works from the OT tier."
            onPick={() => set("route", "mesh")}
          />
          <RouteChoice
            active={form.route === "direct"}
            title="Direct endpoint"
            body="Post to an OpenAI-compatible endpoint with a key stored in this app. Azure AI Foundry, OpenAI, OpenRouter, Ollama. Nothing governs or records it."
            onPick={() => set("route", "direct")}
          />
        </div>

        {form.route === "mesh" && (
          <div className="grid gap-4 rounded-lg border border-border bg-bg p-3 sm:grid-cols-2">
            <Field label="Backbone" hint="Seeded from the bridge's broker. mqtt reaches a Solace backbone over its MQTT listener.">
              <div className="flex gap-2">
                <select className={cx(inputCls, "w-28 shrink-0")} value={form.meshProtocol}
                        onChange={(e) => set("meshProtocol", e.target.value as Form["meshProtocol"])}>
                  <option value="">auto</option>
                  <option value="mqtt">mqtt</option>
                  <option value="nats">nats</option>
                </select>
                <input className={inputCls} value={form.meshHost} placeholder="l3-edge-solace"
                       onChange={(e) => set("meshHost", e.target.value)} />
                <input type="number" className={cx(inputCls, "w-24 shrink-0")} value={form.meshPort || ""}
                       placeholder="1883" onChange={(e) => set("meshPort", Number(e.target.value) || 0)} />
              </div>
            </Field>
            <Field label="Application id" hint="How the gateway names this app in its ledger. It registers on first contact; somebody then allows it a model under Applications.">
              <input className={inputCls} value={form.meshAppId} onChange={(e) => set("meshAppId", e.target.value)} />
            </Field>
            <Field label="Backbone user" hint="The same credential the bridge uses. Leave blank on a broker that does not ask.">
              <input className={inputCls} value={form.meshUsername} onChange={(e) => set("meshUsername", e.target.value)} />
            </Field>
            <Field label="Backbone password" hint={data.meshPasswordSet ? "Stored. Leave blank to keep it." : "Never returned to this page."}>
              <input type="password" className={inputCls} value={form.meshPassword}
                     placeholder={data.meshPasswordSet ? "••••••••  (unchanged)" : ""}
                     onChange={(e) => set("meshPassword", e.target.value)} />
            </Field>
            <Field label="Model" hint="Leave empty and the gateway picks this app's allowed default.">
              <input className={inputCls} value={form.meshModel} placeholder="(gateway default)"
                     onChange={(e) => set("meshModel", e.target.value)} />
            </Field>
            <Field label="Timeout (s)" hint="A model behind two mesh hops is slow; a lost reply costs the whole deadline. 120 is the platform's figure.">
              <input type="number" className={inputCls} value={form.meshTimeout}
                     onChange={(e) => set("meshTimeout", Number(e.target.value) || 120)} />
            </Field>
          </div>
        )}

        <div className={cx("grid gap-4 sm:grid-cols-2", form.route === "mesh" && "opacity-60")}>
          <Field
            label="Endpoint"
            hint={
              envLocked.endpoint
                ? "Set by UDS_LLM_ENDPOINT — the environment wins over anything saved here."
                : "Base URL, e.g. https://your-resource.openai.azure.com/openai/v1 or http://localhost:11434/v1"
            }
          >
            <input
              className={inputCls}
              value={form.endpoint}
              placeholder="https://…/v1"
              onChange={(e) => set("endpoint", e.target.value)}
            />
          </Field>
          <Field
            label="Model / deployment"
            hint={envLocked.model ? "Set by UDS_LLM_MODEL." : "The deployment name at that endpoint."}
          >
            <input
              className={inputCls}
              value={form.model}
              placeholder="gpt-4.1"
              onChange={(e) => set("model", e.target.value)}
            />
          </Field>
          <Field
            label="API key"
            hint={
              envLocked.apiKey
                ? "Set by UDS_LLM_API_KEY."
                : data.apiKeySet
                  ? "A key is stored. Leave blank to keep it; type a new one to replace it."
                  : "Stored in agent_config.json and never sent back to this page."
            }
          >
            <input
              type="password"
              className={inputCls}
              value={form.apiKey}
              placeholder={data.apiKeySet ? "••••••••  (unchanged)" : "sk-…"}
              onChange={(e) => set("apiKey", e.target.value)}
            />
          </Field>
          <Field label="Tool steps per turn" hint="How many tool round-trips one reply may take. Modelling a site needs a lot.">
            <input
              type="number"
              min={1}
              max={100}
              className={inputCls}
              value={form.maxSteps}
              onChange={(e) => set("maxSteps", Number(e.target.value) || 24)}
            />
          </Field>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-border bg-bg px-3 py-2.5">
          <div className="pr-4">
            <div className="text-sm font-medium text-fg">Let the agent change the model</div>
            <div className="text-xs text-fg-muted">
              Off, it can read and analyse but never writes. On, edits apply immediately and every
              one is snapshotted — undo them from the Agent page.
            </div>
          </div>
          <Toggle on={form.allowWrites} onChange={(v) => set("allowWrites", v)} />
        </div>

        <Field
          label="Extra instructions"
          hint="Appended to the agent's system prompt on every turn — house conventions, things to avoid."
        >
          <textarea
            rows={3}
            className="w-full rounded-lg border border-border bg-bg p-2 text-sm text-fg outline-none focus:border-accent"
            value={form.systemPromptExtra}
            placeholder="Prefer the asset library over hand-written tags. Never start the simulation without asking."
            onChange={(e) => set("systemPromptExtra", e.target.value)}
          />
        </Field>

        <McpSection
          settings={data}
          enabled={form.mcpEnabled}
          allowWrites={form.mcpAllowWrites}
          onEnabled={(v) => set("mcpEnabled", v)}
          onAllowWrites={(v) => set("mcpAllowWrites", v)}
          onRotate={() => save.mutate({ ...form, mcpToken: "" } as Partial<Form>)}
        />
      </div>
    </Card>
  );
}

function RouteChoice({
  active,
  title,
  body,
  onPick,
}: {
  active: boolean;
  title: string;
  body: string;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className={cx(
        "rounded-lg border p-3 text-left transition-tokens",
        active ? "border-accent bg-accent-soft" : "border-border bg-bg hover:border-fg-faint",
      )}
    >
      <div className={cx("text-sm font-medium", active ? "text-accent" : "text-fg")}>{title}</div>
      <div className="mt-1 text-[11px] leading-relaxed text-fg-muted">{body}</div>
    </button>
  );
}

function McpSection({
  settings,
  enabled,
  allowWrites,
  onEnabled,
  onAllowWrites,
  onRotate,
}: {
  settings: Settings;
  enabled: boolean;
  allowWrites: boolean;
  onEnabled: (v: boolean) => void;
  onAllowWrites: (v: boolean) => void;
  onRotate: () => void;
}) {
  const url = `${window.location.origin}${window.location.pathname.replace(/\/app.*$/, "")}/mcp`;
  return (
    <div className="rounded-lg border border-border">
      <div className="flex items-start gap-3 border-b border-border px-3 py-2.5">
        <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
          <Plug size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-fg">MCP server</div>
          <div className="text-xs text-fg-muted">
            Lets an external agent drive this UDS with the same tools the built-in one uses.
          </div>
        </div>
        <Toggle on={enabled} onChange={onEnabled} />
      </div>

      {enabled && (
        <div className="flex flex-col gap-3 px-3 py-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[13px] font-medium text-fg">Allow writes over MCP</div>
              <div className="text-[11px] text-fg-muted">
                Off, external agents get the read-only tools only.
              </div>
            </div>
            <Toggle on={allowWrites} onChange={onAllowWrites} />
          </div>

          <CopyRow label="Endpoint" value={url} />
          <CopyRow label="Bearer token" value={settings.mcpToken} secret />

          <button
            onClick={onRotate}
            className="flex items-center gap-1.5 self-start text-[11px] text-fg-muted hover:text-fg"
          >
            <RefreshCw size={11} /> Rotate token
          </button>

          <div>
            <div className="mb-1 text-[11px] font-medium text-fg-muted">
              For a local agent (Claude Desktop / Claude Code), over stdio:
            </div>
            <pre className="overflow-x-auto rounded-lg border border-border bg-bg p-2.5 font-mono text-[11px] leading-relaxed text-fg">
{`python -m uds_mcp stdio --uds ${window.location.origin}`}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function CopyRow({ label, value, secret }: { label: string; value: string; secret?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [shown, setShown] = useState(!secret);
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium text-fg-muted">{label}</div>
      <div className="flex items-center gap-1.5">
        <code
          className={cx(
            "min-w-0 flex-1 truncate rounded-lg border border-border bg-bg px-2.5 py-1.5 font-mono text-[11px] text-fg",
            !shown && "select-none tracking-widest",
          )}
        >
          {shown ? value : "•".repeat(32)}
        </code>
        {secret && (
          <button
            onClick={() => setShown((s) => !s)}
            className="rounded-lg border border-border px-2 py-1.5 text-[11px] text-fg-muted hover:text-fg"
          >
            {shown ? "Hide" : "Show"}
          </button>
        )}
        <button
          onClick={() => {
            navigator.clipboard?.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          title="Copy"
          className="rounded-lg border border-border p-1.5 text-fg-muted hover:text-fg"
        >
          {copied ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}
