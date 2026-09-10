// Model-authored SVG is untrusted markup: sanitize to an allowlist before it
// ever reaches the DOM. Scripts, foreignObject, external refs and event
// handlers are stripped — an <svg> from an LLM must never be able to run code
// or phone home.

const ALLOWED_TAGS = new Set([
  "svg", "g", "defs", "title", "desc", "path", "rect", "circle", "ellipse", "line",
  "polyline", "polygon", "text", "tspan", "marker", "linearGradient", "radialGradient",
  "stop", "clipPath", "mask", "pattern", "use", "symbol", "filter", "feGaussianBlur",
  "feOffset", "feMerge", "feMergeNode", "feColorMatrix", "feBlend",
]);

const ALLOWED_ATTR_PREFIXES = ["aria-", "data-"];
const ALLOWED_ATTRS = new Set([
  "viewBox", "xmlns", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy",
  "r", "rx", "ry", "d", "points", "fill", "fill-opacity", "fill-rule", "stroke",
  "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray",
  "stroke-dashoffset", "stroke-opacity", "opacity", "transform", "class", "style",
  "font-size", "font-family", "font-weight", "text-anchor", "dominant-baseline", "dy", "dx",
  "id", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
  "patternUnits", "markerWidth", "markerHeight", "refX", "refY", "orient", "clip-path",
  "mask", "filter", "stdDeviation", "result", "in", "in2", "mode", "values", "type",
  "preserveAspectRatio", "vector-effect", "xlink:href", "href",
]);

/** url(#local) is fine; url(http://…) and javascript: are not. */
function safeStyle(value: string): string {
  const lowered = value.toLowerCase();
  if (lowered.includes("javascript:") || lowered.includes("expression(")) return "";
  if (/url\(\s*['"]?(?!#)/i.test(value)) return "";
  return value;
}

function safeHref(value: string): string | null {
  return value.trim().startsWith("#") ? value : null; // only internal refs
}

export function sanitizeSvg(markup: string): { svg: string | null; error: string | null } {
  if (typeof window === "undefined") return { svg: null, error: "no DOM" };
  const doc = new DOMParser().parseFromString(markup.trim(), "image/svg+xml");
  if (doc.querySelector("parsererror")) return { svg: null, error: "the SVG is not well-formed XML" };

  const root = doc.documentElement;
  if (root.tagName.toLowerCase() !== "svg") return { svg: null, error: "content is not an <svg> element" };

  const walk = (node: Element): void => {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (!ALLOWED_TAGS.has(tag)) {
        child.remove();
        continue;
      }
      for (const attr of Array.from(child.attributes)) {
        const name = attr.name;
        const lower = name.toLowerCase();
        if (lower.startsWith("on")) {
          child.removeAttribute(name); // no event handlers, ever
          continue;
        }
        if (ALLOWED_ATTR_PREFIXES.some((p) => lower.startsWith(p))) continue;
        if (!ALLOWED_ATTRS.has(name)) {
          child.removeAttribute(name);
          continue;
        }
        if (name === "style") {
          const cleaned = safeStyle(attr.value);
          if (cleaned) child.setAttribute("style", cleaned);
          else child.removeAttribute("style");
        }
        if (name === "href" || name === "xlink:href") {
          const safe = safeHref(attr.value);
          if (safe) child.setAttribute(name, safe);
          else child.removeAttribute(name);
        }
      }
      walk(child);
    }
  };

  for (const attr of Array.from(root.attributes)) {
    if (attr.name.toLowerCase().startsWith("on") || !ALLOWED_ATTRS.has(attr.name)) {
      if (!ALLOWED_ATTR_PREFIXES.some((p) => attr.name.toLowerCase().startsWith(p))) {
        root.removeAttribute(attr.name);
      }
    }
  }
  walk(root);

  // Responsive by default: the model rarely gets sizing right.
  root.removeAttribute("width");
  root.removeAttribute("height");
  if (!root.getAttribute("viewBox")) return { svg: null, error: "the SVG has no viewBox" };

  return { svg: new XMLSerializer().serializeToString(root), error: null };
}

export function SvgBlock({ raw }: { raw: string }) {
  const { svg, error } = sanitizeSvg(raw);
  if (!svg) {
    return (
      <div className="my-3 rounded-xl border border-warn/40 bg-warn-soft/50 p-3 text-xs text-warn">
        Could not render this SVG: {error}
      </div>
    );
  }
  return (
    <div
      className="my-3 overflow-hidden rounded-xl border border-border bg-surface p-3 [&_svg]:h-auto [&_svg]:w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
