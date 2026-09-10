import { useMemo, useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import "highlight.js/styles/atom-one-dark.css";

// The languages an agent modelling a UNS actually emits: JSON (policies,
// payloads), YAML (compose, configs), XML (OPC-UA nodesets), the odd shell
// line and Python snippet. Registering only these keeps highlight.js small.
hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("python", python);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("sh", bash);

const EXT: Record<string, string> = { json: "json", yaml: "yaml", yml: "yaml", xml: "xml", csv: "csv",
  python: "py", bash: "sh", shell: "sh", sh: "sh", txt: "txt", md: "md" };

/** Copy-to-clipboard for a code fence, or a download for the ones worth keeping. */
export function copyText(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}

export function downloadText(name: string, text: string, mime = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const lang = (language || "").toLowerCase();

  const html = useMemo(() => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value;
      } catch {
        /* fall through to plain */
      }
    }
    return undefined;
  }, [lang, code]);

  const copy = async () => {
    try {
      await copyText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-border">
      <div className="flex items-center justify-between border-b border-border bg-surface-2 px-3 py-1">
        <span className="text-[10px] font-medium uppercase tracking-wider text-fg-faint">
          {lang || "text"}
        </span>
        <span className="flex items-center gap-0.5">
          {EXT[lang] && code.split("\n").length > 3 && (
            <button
              onClick={() => downloadText(`agent.${EXT[lang]}`, code)}
              className="grid h-6 w-6 place-items-center rounded text-fg-faint hover:bg-surface-3 hover:text-fg"
              title="Download"
            >
              <Download size={12} />
            </button>
          )}
          <button
            onClick={copy}
            className="grid h-6 w-6 place-items-center rounded text-fg-faint hover:bg-surface-3 hover:text-fg"
            title="Copy"
          >
            {copied ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
          </button>
        </span>
      </div>
      <pre className="overflow-x-auto bg-[#282c34] p-3 text-[12px] leading-relaxed text-[#abb2bf]">
        {html !== undefined ? (
          <code className="font-mono" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code className="font-mono">{code}</code>
        )}
      </pre>
    </div>
  );
}
