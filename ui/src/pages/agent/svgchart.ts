// Hand-rolled chart geometry (family rule: no chart library). Pure functions —
// the React component just maps these to SVG elements. Colors come from CSS
// variables, so light/dark theming is free.

export type ChartType = "line" | "area" | "bar" | "scatter";
export type XKind = "time" | "linear" | "category";

export interface ChartSpec {
  type: ChartType;
  title?: string;
  x?: { kind?: XKind; label?: string };
  y?: { label?: string; unit?: string };
  stacked?: boolean;
  series: Array<{ name: string; data: Array<[string | number, number | null]> }>;
}

export interface Scales {
  xOf: (v: string | number) => number;
  yOf: (v: number) => number;
  xTicks: Array<{ pos: number; label: string }>;
  yTicks: Array<{ pos: number; label: string }>;
  bandWidth: number;
  categories: string[];
}

export const PLOT = { width: 720, height: 300, left: 52, right: 14, top: 16, bottom: 34 };

/** Series colors: accent first, then a small distinct ramp that works in both themes. */
export const SERIES_COLORS = [
  "var(--accent)",
  "var(--state-ok)",
  "var(--state-warn)",
  "var(--state-err)",
  "#a855f7",
  "#0891b2",
];

export function parseChartSpec(raw: string): { spec: ChartSpec | null; error: string | null } {
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return { spec: null, error: "chart spec must be a JSON object" };
    if (!Array.isArray(parsed.series) || parsed.series.length === 0) {
      return { spec: null, error: "chart spec needs a non-empty `series` array" };
    }
    for (const s of parsed.series) {
      if (!Array.isArray(s.data)) return { spec: null, error: `series "${s.name ?? "?"}" has no data array` };
    }
    return { spec: parsed as ChartSpec, error: null };
  } catch (err) {
    return { spec: null, error: err instanceof Error ? err.message : "invalid JSON" };
  }
}

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = Math.abs(min) || 1;
    min -= pad * 0.5;
    max += pad * 0.5;
  }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.001; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

function formatValue(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (v / 1e3).toFixed(1) + "k";
  if (abs >= 100) return v.toFixed(0);
  if (abs >= 1) return v.toFixed(1);
  if (abs === 0) return "0";
  return v.toPrecision(2);
}

export function formatX(v: string | number, kind: XKind): string {
  if (kind === "time") {
    const d = new Date(v);
    if (isNaN(d.getTime())) return String(v);
    const sameDay = Date.now() - d.getTime() < 86400_000;
    return sameDay
      ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  if (kind === "linear") return formatValue(Number(v));
  return String(v);
}

export function buildScales(spec: ChartSpec): Scales {
  const kind: XKind = spec.x?.kind ?? "category";
  const isBand = kind === "category" || spec.type === "bar";
  const innerW = PLOT.width - PLOT.left - PLOT.right;
  const innerH = PLOT.height - PLOT.top - PLOT.bottom;

  const allPoints = spec.series.flatMap((s) => s.data);
  const yValues = allPoints.map((p) => p[1]).filter((v): v is number => typeof v === "number" && isFinite(v));

  let yMin = Math.min(...yValues, 0 === 0 ? Math.min(...yValues) : 0);
  let yMax = Math.max(...yValues);
  if (spec.stacked && (spec.type === "bar" || spec.type === "area")) {
    const sums = new Map<string, number>();
    for (const s of spec.series) for (const [x, y] of s.data) sums.set(String(x), (sums.get(String(x)) ?? 0) + (y ?? 0));
    yMax = Math.max(...sums.values());
  }
  if (!isFinite(yMin) || !isFinite(yMax)) {
    yMin = 0;
    yMax = 1;
  }
  // Bars read from a zero baseline; lines get a tight, padded range.
  if (spec.type === "bar" && yMin > 0) yMin = 0;
  const ticks = niceTicks(yMin, yMax);
  const yLo = Math.min(yMin, ticks[0]);
  const yHi = Math.max(yMax, ticks[ticks.length - 1]);

  const categories: string[] = [];
  const seen = new Set<string>();
  for (const s of spec.series)
    for (const [x] of s.data) {
      const key = String(x);
      if (!seen.has(key)) {
        seen.add(key);
        categories.push(key);
      }
    }

  const numericX = kind === "time" ? categories.map((c) => new Date(c).getTime()) : categories.map(Number);
  const xLo = Math.min(...numericX);
  const xHi = Math.max(...numericX);

  const bandWidth = isBand ? innerW / Math.max(categories.length, 1) : 0;

  const xOf = (v: string | number): number => {
    if (isBand) {
      const i = categories.indexOf(String(v));
      return PLOT.left + bandWidth * (i + 0.5);
    }
    const n = kind === "time" ? new Date(v).getTime() : Number(v);
    if (xHi === xLo) return PLOT.left + innerW / 2;
    return PLOT.left + ((n - xLo) / (xHi - xLo)) * innerW;
  };

  const yOf = (v: number): number => {
    if (yHi === yLo) return PLOT.top + innerH / 2;
    return PLOT.top + innerH - ((v - yLo) / (yHi - yLo)) * innerH;
  };

  // Thin out x labels so they never collide.
  const maxLabels = Math.max(2, Math.floor(innerW / 90));
  const stride = Math.ceil(categories.length / maxLabels);
  const xTicks = categories
    .filter((_, i) => i % stride === 0)
    .map((c) => ({ pos: xOf(c), label: formatX(kind === "time" ? c : isNaN(Number(c)) ? c : Number(c), kind) }));

  return {
    xOf,
    yOf,
    xTicks,
    yTicks: ticks.map((t) => ({ pos: yOf(t), label: formatValue(t) })),
    bandWidth,
    categories,
  };
}

export function linePath(data: Array<[string | number, number | null]>, scales: Scales): string {
  let path = "";
  let pen = false;
  for (const [x, y] of data) {
    if (y === null || !isFinite(y)) {
      pen = false; // gap in the data — lift the pen rather than draw through it
      continue;
    }
    const cmd = pen ? "L" : "M";
    path += `${cmd}${scales.xOf(x).toFixed(2)},${scales.yOf(y).toFixed(2)}`;
    pen = true;
  }
  return path;
}

export function areaPath(data: Array<[string | number, number | null]>, scales: Scales): string {
  const points = data.filter(([, y]) => y !== null && isFinite(y as number)) as Array<[string | number, number]>;
  if (points.length === 0) return "";
  const baseline = PLOT.height - PLOT.bottom;
  const top = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${scales.xOf(x).toFixed(2)},${scales.yOf(y).toFixed(2)}`);
  return `${top.join("")}L${scales.xOf(points[points.length - 1][0]).toFixed(2)},${baseline}L${scales
    .xOf(points[0][0])
    .toFixed(2)},${baseline}Z`;
}
