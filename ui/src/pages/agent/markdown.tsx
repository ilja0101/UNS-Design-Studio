import { type ReactNode } from "react";

/** A deliberately small Markdown subset, rendered as React nodes.
 *
 *  The agent writes short operational prose — a sentence, a bullet list, the
 *  odd path or JSON snippet — not documents. That needs fenced code, inline
 *  code, bold, headings and lists, and nothing else. Building those as React
 *  elements (rather than pulling in a Markdown library and an HTML sanitiser)
 *  keeps the bundle where it is and makes injection structurally impossible:
 *  no path in here produces raw HTML.
 */
export function Markdown({ text }: { text: string }) {
  return <>{blocks(text ?? "")}</>;
}

function blocks(src: string): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++; // closing fence
      out.push(
        <pre
          key={key++}
          className="my-2 overflow-x-auto rounded-lg border border-border bg-surface-2 p-3 text-[12px] leading-relaxed"
        >
          <code className="font-mono text-fg">{body.join("\n")}</code>
          {lang && <span className="sr-only">{lang}</span>}
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      out.push(
        <p key={key++} className="mt-3 mb-1 text-[13px] font-semibold text-fg">
          {inline(heading[2])}
        </p>,
      );
      i++;
      continue;
    }

    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        i++;
      }
      const Tag = ordered ? "ol" : "ul";
      out.push(
        <Tag
          key={key++}
          className={`my-1.5 ml-4 flex list-outside flex-col gap-1 ${
            ordered ? "list-decimal" : "list-disc"
          }`}
        >
          {items.map((it, n) => (
            <li key={n} className="text-[13px] leading-relaxed">
              {inline(it)}
            </li>
          ))}
        </Tag>,
      );
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].startsWith("```") &&
      !/^\s*([-*]|\d+\.)\s+/.test(lines[i]) &&
      !/^#{1,4}\s/.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    out.push(
      <p key={key++} className="my-1.5 text-[13px] leading-relaxed">
        {inline(para.join(" "))}
      </p>,
    );
  }
  return out;
}

/** `code`, **bold** and *italic* — everything else stays literal text. */
function inline(src: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)/g;
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;

  while ((m = pattern.exec(src)) !== null) {
    if (m.index > last) out.push(src.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("`")) {
      out.push(
        <code
          key={key++}
          className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[12px] text-fg"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      out.push(
        <strong key={key++} className="font-semibold">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      out.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
    last = m.index + token.length;
  }
  if (last < src.length) out.push(src.slice(last));
  return out;
}
