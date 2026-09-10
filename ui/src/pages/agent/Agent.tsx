import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ArrowUp,
  MessageSquarePlus,
  PanelRightClose,
  PanelRightOpen,
  Settings2,
  Square,
  Trash2,
} from "lucide-react";
import { agentChat, api, type AgentEvent, type ChatMessage } from "../../api";
import { Button, cx } from "../../components/ui";
import { SidePanel } from "./SidePanel";
import { Transcript, type ToolEntry, type Turn } from "./Transcript";

/** Suggestions that show the agent's actual range on an empty conversation. */
const STARTERS = [
  {
    title: "Model a site from our topic policy",
    prompt:
      "Read the active topic policy, then model a new site under the enterprise: two production " +
      "areas with realistic equipment from the asset library, plus utilities. Check it against " +
      "the policy and fix anything it flags.",
  },
  {
    title: "Set our topic policy",
    prompt:
      "Our UNS topic policy: NATS separator '.', prefix 'uns', levels enterprise > site > area > " +
      "workUnit, all names lower-kebab, tag names snake_case, tag qualifiers limited to data, " +
      "command and state. Store that as the policy, then tell me how the current model measures up.",
  },
  {
    title: "Audit what we publish today",
    prompt:
      "Give me an overview of the current model, check it against the topic policy, and show me a " +
      "sample of the topics it publishes. Summarise what would need to change to be compliant.",
  },
  {
    title: "Add closed-loop setpoints",
    prompt:
      "Find the pumps in the model and add writable speed-setpoint command tags to each, so an " +
      "optimiser can drive them. Keep the naming consistent with the topic policy.",
  },
];

export function Agent() {
  const qc = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [live, setLive] = useState<Turn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const settings = useQuery({ queryKey: ["agent-settings"], queryFn: api.agentSettings });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const active = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: !!conversationId && !streaming,
  });

  const remove = useMutation({
    mutationFn: api.conversationDelete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });

  // While a turn streams, `live` is the source of truth; between turns the
  // persisted conversation is, so a reload shows exactly what happened.
  const turns = streaming || live.length ? live : replay(active.data?.messages ?? []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, streaming]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || streaming) return;
      setError(null);
      setDraft("");

      const base = replay(active.data?.messages ?? []);
      const userTurn: Turn = { key: `u-${Date.now()}`, role: "user", text: message, tools: [] };
      const agentTurn: Turn = {
        key: `a-${Date.now()}`,
        role: "assistant",
        text: "",
        tools: [],
        streaming: true,
      };
      setLive([...base, userTurn, agentTurn]);
      setStreaming(true);

      const controller = new AbortController();
      abort.current = controller;
      const patch = (fn: (t: Turn) => Turn) =>
        setLive((prev) => prev.map((t) => (t.key === agentTurn.key ? fn(t) : t)));

      try {
        for await (const ev of agentChat(
          { message, conversation: conversationId ?? undefined },
          controller.signal,
        )) {
          applyEvent(ev, { patch, setConversationId, setError });
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(String(e));
      } finally {
        abort.current = null;
        setStreaming(false);
        patch((t) => ({ ...t, streaming: false }));
        qc.invalidateQueries({ queryKey: ["conversations"] });
        // The agent's tools change the model underneath the rest of the app.
        qc.invalidateQueries({ queryKey: ["uns"] });
        qc.invalidateQueries({ queryKey: ["graph"] });
        qc.invalidateQueries({ queryKey: ["policy-check"] });
        qc.invalidateQueries({ queryKey: ["agent-snapshots"] });
      }
    },
    [active.data, conversationId, qc, streaming],
  );

  const startNew = () => {
    abort.current?.abort();
    setConversationId(null);
    setLive([]);
    setError(null);
  };

  const openConversation = (id: string) => {
    abort.current?.abort();
    setConversationId(id);
    setLive([]);
    setError(null);
  };

  const configured = settings.data?.configured ?? false;

  return (
    <div className="flex h-full min-h-0">
      <ConversationList
        items={conversations.data?.conversations ?? []}
        activeId={conversationId}
        onOpen={openConversation}
        onNew={startNew}
        onDelete={(id) => {
          remove.mutate(id);
          if (id === conversationId) startNew();
        }}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border px-5 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold text-fg">
              {turns.length ? active.data?.title ?? "New chat" : "Agent"}
            </h2>
            <p className="truncate text-[11px] text-fg-muted">
              {configured
                ? `Models the UNS through ${settings.data?.model} — every edit is snapshotted`
                : "No LLM endpoint configured yet"}
            </p>
          </div>
          <button
            onClick={() => setPanelOpen((o) => !o)}
            title={panelOpen ? "Hide policy panel" : "Show policy panel"}
            className="rounded-lg border border-border bg-surface p-2 text-fg-muted hover:text-fg"
          >
            {panelOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="mx-auto w-full max-w-3xl">
            {!configured && <NotConfigured />}
            {turns.length === 0 && configured && <Starters onPick={send} />}
            <Transcript turns={turns} />
            {error && (
              <p className="mt-4 rounded-lg border border-err/40 bg-err-soft px-3 py-2 text-[12px] text-err">
                {error}
              </p>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => send(draft)}
          onStop={() => abort.current?.abort()}
          streaming={streaming}
          disabled={!configured}
        />
      </section>

      {panelOpen && <SidePanel />}
    </div>
  );
}

// ── event handling ──────────────────────────────────────────────────────────

function applyEvent(
  ev: AgentEvent,
  ctx: {
    patch: (fn: (t: Turn) => Turn) => void;
    setConversationId: (id: string) => void;
    setError: (m: string) => void;
  },
) {
  switch (ev.type) {
    case "start":
      ctx.setConversationId(ev.conversation);
      break;
    case "delta":
      ctx.patch((t) => ({ ...t, text: t.text + ev.text }));
      break;
    case "tool_call":
      ctx.patch((t) => ({
        ...t,
        tools: [...t.tools, { id: ev.id, name: ev.name, args: ev.args, pending: true }],
      }));
      break;
    case "tool_result":
      ctx.patch((t) => ({
        ...t,
        tools: t.tools.map((x) =>
          x.id === ev.id
            ? { ...x, pending: false, ok: ev.ok, summary: ev.summary, result: ev.result }
            : x,
        ),
      }));
      break;
    case "done":
      if (ev.message) ctx.patch((t) => ({ ...t, text: `${t.text}\n\n_${ev.message}_` }));
      break;
    case "error":
      ctx.setError(ev.message);
      break;
  }
}

/** Rebuild renderable turns from a stored conversation.
 *
 *  Storage is OpenAI-shaped (assistant messages carry tool_calls, results come
 *  back as separate `tool` messages); the transcript wants tool calls attached
 *  to the assistant turn that made them, so results are folded back in here.
 */
function replay(messages: ChatMessage[]): Turn[] {
  const turns: Turn[] = [];
  const pending = new Map<string, ToolEntry>();

  messages.forEach((m, i) => {
    if (m.role === "user") {
      turns.push({ key: `m${i}`, role: "user", text: m.content, tools: [] });
      return;
    }
    if (m.role === "assistant") {
      const tools: ToolEntry[] = (m.tool_calls ?? []).map((tc) => {
        const entry: ToolEntry = {
          id: tc.id,
          name: tc.function.name,
          args: safeParse(tc.function.arguments),
          pending: true,
        };
        pending.set(tc.id, entry);
        return entry;
      });
      // Consecutive assistant messages are one logical turn: the model spoke,
      // ran tools, then spoke again. Merging keeps the transcript readable.
      const last = turns[turns.length - 1];
      if (last?.role === "assistant") {
        last.text = [last.text, m.content].filter(Boolean).join("\n\n");
        last.tools = [...last.tools, ...tools];
      } else {
        turns.push({ key: `m${i}`, role: "assistant", text: m.content, tools });
      }
      return;
    }
    if (m.role === "tool" && m.tool_call_id) {
      const entry = pending.get(m.tool_call_id);
      if (entry) {
        entry.pending = false;
        entry.ok = m.ok ?? true;
        entry.summary = m.summary ?? "";
        entry.result = safeParse(m.content);
      }
    }
  });
  return turns;
}

function safeParse(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw || "{}");
    return parsed && typeof parsed === "object" ? parsed : { value: parsed };
  } catch {
    return { raw };
  }
}

// ── pieces ──────────────────────────────────────────────────────────────────

function ConversationList({
  items,
  activeId,
  onOpen,
  onNew,
  onDelete,
}: {
  items: Array<{ id: string; title: string; updatedAt: string }>;
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface">
      <div className="p-3">
        <button
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-[13px] font-medium text-accent-fg hover:bg-accent-hover"
        >
          <MessageSquarePlus size={14} />
          New chat
        </button>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {items.length === 0 && (
          <p className="px-2 py-3 text-[11px] text-fg-faint">No conversations yet.</p>
        )}
        {items.map((c) => (
          <div
            key={c.id}
            className={cx(
              "group mb-0.5 flex items-center gap-1 rounded-lg pr-1",
              c.id === activeId ? "bg-accent-soft" : "hover:bg-surface-2",
            )}
          >
            <button
              onClick={() => onOpen(c.id)}
              className="min-w-0 flex-1 px-2 py-2 text-left"
              title={c.title}
            >
              <span
                className={cx(
                  "block truncate text-[12px]",
                  c.id === activeId ? "font-medium text-accent" : "text-fg",
                )}
              >
                {c.title}
              </span>
              <span className="block text-[10px] text-fg-faint">{c.updatedAt.slice(0, 10)}</span>
            </button>
            <button
              onClick={() => onDelete(c.id)}
              title="Delete conversation"
              className="rounded p-1 text-fg-faint opacity-0 transition-tokens hover:text-err group-hover:opacity-100"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </nav>
    </aside>
  );
}

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  disabled: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  // Grow with the content up to a ceiling, then scroll — a pasted policy
  // document should be visible, not squeezed into two lines.
  //
  // Collapse to 0 before measuring, not to "auto": the textarea sits in a flex
  // row whose own height is derived from it, so "auto" can resolve against the
  // height we set last time and the box ratchets straight up to the ceiling and
  // stays there, empty. From 0, scrollHeight is the content and nothing else.
  //
  // An empty composer never measures: it is one row by CSS, and letting the
  // measurement run on empty content is how it ends up stuck at the ceiling if
  // the layout is mid-flight when the effect fires.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!value) {
      el.style.height = "";
      return;
    }
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [value]);

  return (
    <div className="border-t border-border px-5 py-3">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-xl border border-border bg-surface p-2 focus-within:border-accent">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          placeholder={
            disabled
              ? "Configure an LLM endpoint in Settings to chat here"
              : "Paste a topic policy, or ask for a plant to be modelled…"
          }
          className="max-h-[260px] min-h-[36px] flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[13px] text-fg outline-none placeholder:text-fg-faint disabled:opacity-60"
        />
        {streaming ? (
          <button
            onClick={onStop}
            title="Stop"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-border text-fg-muted hover:text-fg"
          >
            <Square size={13} />
          </button>
        ) : (
          <button
            onClick={onSend}
            disabled={disabled || !value.trim()}
            title="Send"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-fg hover:bg-accent-hover disabled:opacity-40"
          >
            <ArrowUp size={15} />
          </button>
        )}
      </div>
      {!disabled && (
        <p className="mx-auto mt-1.5 w-full max-w-3xl text-[10px] text-fg-faint">
          Enter to send · Shift+Enter for a new line · the agent edits this simulator directly
        </p>
      )}
    </div>
  );
}

function Starters({ onPick }: { onPick: (prompt: string) => void }) {
  const items = useMemo(() => STARTERS, []);
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-fg">Model your UNS by asking</h3>
      <p className="mb-3 text-[12px] text-fg-muted">
        The agent reads and edits this simulator directly — the tree, the tags, the topic policy and
        the running simulation. Everything it changes is snapshotted, so you can undo it.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((s) => (
          <button
            key={s.title}
            onClick={() => onPick(s.prompt)}
            className="rounded-xl border border-border bg-surface p-3 text-left transition-tokens hover:border-accent hover:bg-accent-soft"
          >
            <div className="text-[12px] font-medium text-fg">{s.title}</div>
            <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-fg-muted">
              {s.prompt}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function NotConfigured() {
  return (
    <div className="mb-6 rounded-xl border border-warn/40 bg-warn-soft p-4">
      <h3 className="text-sm font-semibold text-fg">No LLM endpoint configured</h3>
      <p className="mt-1 text-[12px] leading-relaxed text-fg-muted">
        The built-in agent needs an OpenAI-compatible endpoint — Azure AI Foundry, OpenAI,
        OpenRouter, or a local Ollama. Add one under Settings, or skip it entirely and drive this
        UDS from an external agent over MCP: the tools are identical.
      </p>
      <div className="mt-3">
        <Link to="/settings">
          <Button variant="ghost">
            <span className="flex items-center gap-1.5">
              <Settings2 size={13} /> Open Settings
            </span>
          </Button>
        </Link>
      </div>
    </div>
  );
}
