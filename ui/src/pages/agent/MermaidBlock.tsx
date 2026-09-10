import { useEffect, useRef, useState } from "react";

// Mermaid is ~500 kB — loaded only when a diagram actually appears in a chat,
// so the studio's own bundle stays where it is. Same fence as IAI-V2 and the
// AMIX Ask AI panels: ```mermaid.
let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
let renderSeq = 0;

async function getMermaid(dark: boolean) {
  if (!mermaidPromise) mermaidPromise = import("mermaid").then((m) => m.default);
  const mermaid = await mermaidPromise;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict", // no click handlers / html labels from model output
    theme: dark ? "dark" : "default",
    fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif",
  });
  return mermaid;
}

/** Follows the `dark` class on <html> without owning it (theme.ts does). */
export function useIsDark(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const obs = new MutationObserver(() =>
      setDark(document.documentElement.classList.contains("dark")),
    );
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

export function MermaidBlock({ raw }: { raw: string }) {
  const dark = useIsDark();
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    setError(null);
    (async () => {
      try {
        const mermaid = await getMermaid(dark);
        const id = `mmd-${++renderSeq}`;
        const { svg: out } = await mermaid.render(id, raw);
        if (mounted.current) setSvg(out);
      } catch (err) {
        if (mounted.current) setError(err instanceof Error ? err.message : "could not render diagram");
      }
    })();
    return () => {
      mounted.current = false;
    };
  }, [raw, dark]);

  if (error) {
    return (
      <div className="my-3 rounded-xl border border-warn/40 bg-warn-soft/50 p-3">
        <p className="text-xs text-warn">Could not render this diagram: {error}</p>
        <pre className="mt-2 max-h-32 overflow-auto rounded bg-surface p-2 font-mono text-[10px] text-fg-muted">
          {raw}
        </pre>
      </div>
    );
  }
  if (!svg) return <div className="my-3 h-24 animate-pulse rounded-xl border border-border bg-surface-2/50" />;
  return (
    <div
      className="my-3 overflow-x-auto rounded-xl border border-border bg-surface p-3 [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
