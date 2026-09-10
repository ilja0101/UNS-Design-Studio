import { type ReactNode } from "react";
import { ChartBlock } from "./ChartBlock";
import { CodeBlock } from "./CodeBlock";
import { MermaidBlock } from "./MermaidBlock";
import { SvgBlock } from "./SvgBlock";

/** A deliberately small Markdown subset, rendered as React nodes.
 *
 *  The agent writes short operational prose — a sentence, a bullet list, a
 *  table of what it changed, the odd path or JSON snippet — not documents.
 *  Building the pieces as React elements rather than pulling in a Markdown
 *  library plus an HTML sanitiser keeps injection structurally impossible: the
 *  only raw markup that ever reaches the DOM is a fenced ```svg (allow-listed
 *  tag by tag in SvgBlock) and a Mermaid render in strict mode.
 *
 *  Fences follow the family convention shared with IAI-V2 and the AMIX Ask AI
 *  panels, so one prompt teaches every app the same visual vocabulary:
 *  ```chart (a JSON spec), ```mermaid, ```svg, and any other language as code.
 */
export function Markdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  return <>{blocks(text ?? "", streaming)}</>;
}

const LIST = /^\s*([-*]|\d+\.)\s+/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function blocks(src: string, streaming: boolean): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      const lang = line.slice(3).trim().toLowerCase();
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      const closed = i < lines.length;
      i++; // closing fence
      const code = body.join("\n");
      if (lang === "chart") out.push(<ChartBlock key={key++} raw={code} streaming={streaming && !closed} />);
      else if (lang === "mermaid") {
        // Rendering a half-streamed diagram flashes errors; wait for the fence.
        out.push(closed || !streaming ? <MermaidBlock key={key++} raw={code} /> : <Pending key={key++} />);
      } else if (lang === "svg") out.push(closed || !streaming ? <SvgBlock key={key++} raw={code} /> : <Pending key={key++} />);
      else out.push(<CodeBlock key={key++} language={lang} code={code} />);
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

    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push(<hr key={key++} className="my-3 border-border" />);
      i++;
      continue;
    }

    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const header = cells(line);
      const align = cells(lines[i + 1]).map((c) =>
        c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : "left",
      );
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(<Table key={key++} header={header} align={align} rows={rows} />);
      continue;
    }

    if (line.startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(
        <blockquote
          key={key++}
          className="my-2 border-l-2 border-accent/50 pl-3 text-[13px] leading-relaxed text-fg-muted"
        >
          {blocks(quote.join("\n"), false)}
        </blockquote>,
      );
      continue;
    }

    if (LIST.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length && LIST.test(lines[i])) items.push(lines[i++].replace(LIST, ""));
      const Tag = ordered ? "ol" : "ul";
      out.push(
        <Tag
          key={key++}
          className={`my-1.5 ml-4 flex list-outside flex-col gap-1 ${ordered ? "list-decimal" : "list-disc"}`}
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
      !lines[i].startsWith(">") &&
      !LIST.test(lines[i]) &&
      !/^#{1,4}\s/.test(lines[i]) &&
      !(TABLE_ROW.test(lines[i]) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]))
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

function cells(row: string): string[] {
  const trimmed = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  // A `\|` inside a cell is a literal pipe, not a separator.
  return trimmed.split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, "|").trim());
}

function Table({ header, align, rows }: { header: string[]; align: string[]; rows: string[][] }) {
  const cls = (n: number) => (align[n] === "right" ? "text-right" : align[n] === "center" ? "text-center" : "text-left");
  return (
    <div className="my-2 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-[12px]">
        <thead className="bg-surface-2">
          <tr>
            {header.map((h, n) => (
              <th key={n} className={`px-2.5 py-1.5 font-semibold text-fg ${cls(n)}`}>
                {inline(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, m) => (
            <tr key={m} className="border-t border-border">
              {header.map((_, n) => (
                <td key={n} className={`px-2.5 py-1.5 align-top text-fg ${cls(n)}`}>
                  {inline(r[n] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pending() {
  return <div className="my-3 h-16 animate-pulse rounded-xl border border-border bg-surface-2/50" />;
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
        <code key={key++} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[12px] text-fg">
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
