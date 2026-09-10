import { useState } from "react";
import { AlertTriangle, Check, ChevronRight, Sparkles, Wrench, X } from "lucide-react";
import { type Attachment } from "../../api";
import { cx } from "../../components/ui";
import { AttachmentChip } from "./attachments";
import { Markdown } from "./markdown";

/** A tool call as the transcript sees it: issued, then resolved. */
export interface ToolEntry {
  id: string;
  name: string;
  args: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  result?: Record<string, unknown> | null;
  pending: boolean;
}

/** One rendered turn. Assistant turns own the tool calls they made. */
export interface Turn {
  key: string;
  role: "user" | "assistant";
  text: string;
  tools: ToolEntry[];
  attachments?: Attachment[];
  streaming?: boolean;
}

export function Transcript({ turns }: { turns: Turn[] }) {
  return (
    <div className="flex flex-col gap-5">
      {turns.map((t) =>
        t.role === "user" ? (
          <UserTurn key={t.key} text={t.text} attachments={t.attachments ?? []} />
        ) : (
          <AgentTurn key={t.key} turn={t} />
        ),
      )}
    </div>
  );
}

function UserTurn({ text, attachments }: { text: string; attachments: Attachment[] }) {
  return (
    <div className="flex flex-col items-end gap-1.5">
      {attachments.length > 0 && (
        <div className="flex max-w-[80%] flex-wrap justify-end gap-1.5">
          {attachments.map((a) => (
            <AttachmentChip key={a.id} attachment={a} />
          ))}
        </div>
      )}
      {text && (
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[13px] leading-relaxed text-accent-fg">
          {text}
        </div>
      )}
    </div>
  );
}

function AgentTurn({ turn }: { turn: Turn }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
        <Sparkles size={14} />
      </span>
      <div className="min-w-0 flex-1">
        {turn.tools.length > 0 && (
          <div className="mb-2 flex flex-col gap-1.5">
            {turn.tools.map((t) => (
              <ToolCard key={t.id} entry={t} />
            ))}
          </div>
        )}
        {turn.text ? (
          <div className="text-fg">
            <Markdown text={turn.text} />
          </div>
        ) : (
          turn.streaming &&
          turn.tools.length === 0 && <ThinkingDots />
        )}
        {turn.streaming && turn.text && <span className="ml-0.5 inline-block animate-pulse">▌</span>}
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1.5 text-fg-faint">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-fg-faint"
          style={{ animationDelay: `${i * 160}ms` }}
        />
      ))}
    </div>
  );
}

/** Collapsed by default: the summary line is what a person needs mid-flow, and
 *  the arguments/result are there when something looks wrong. */
function ToolCard({ entry }: { entry: ToolEntry }) {
  const [open, setOpen] = useState(false);
  const failed = entry.ok === false;
  return (
    <div
      className={cx(
        "overflow-hidden rounded-lg border text-[12px]",
        failed ? "border-err/40 bg-err-soft" : "border-border bg-surface-2",
      )}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-surface-3/60"
      >
        <ChevronRight
          size={12}
          className={cx("shrink-0 text-fg-faint transition-transform", open && "rotate-90")}
        />
        {entry.pending ? (
          <Wrench size={12} className="shrink-0 animate-pulse text-accent" />
        ) : failed ? (
          <X size={12} className="shrink-0 text-err" />
        ) : (
          <Check size={12} className="shrink-0 text-ok" />
        )}
        <span className="font-mono font-medium text-fg">{entry.name}</span>
        <span className="min-w-0 flex-1 truncate text-fg-muted">
          {entry.pending ? "running…" : entry.summary}
        </span>
      </button>
      {open && (
        <div className="border-t border-border px-2.5 py-2">
          <Detail label="Arguments" value={entry.args} />
          {!entry.pending && entry.result != null && <Detail label="Result" value={entry.result} />}
          {failed && (
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-err">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>{entry.summary}</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: unknown }) {
  const text = JSON.stringify(value, null, 2) ?? "";
  return (
    <div className="mt-1 first:mt-0">
      <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-fg-faint">
        {label}
      </div>
      <pre className="max-h-56 overflow-auto rounded border border-border bg-bg p-2 font-mono text-[11px] leading-relaxed text-fg">
        {text.length > 4000 ? text.slice(0, 4000) + "\n…" : text}
      </pre>
    </div>
  );
}
