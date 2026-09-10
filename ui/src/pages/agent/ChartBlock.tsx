import { useMemo, useRef, useState } from "react";
import { AlertTriangle, LineChart as LineChartIcon } from "lucide-react";
import {
  PLOT,
  SERIES_COLORS,
  areaPath,
  buildScales,
  formatX,
  linePath,
  parseChartSpec,
  type ChartSpec,
  type XKind,
} from "./svgchart";
import { cx } from "../../components/ui";

// Renders a ```chart fence. Theme-aware by construction: every colour is a CSS
// variable, so the same SVG works in light and dark.

export function ChartBlock({ raw, streaming = false }: { raw: string; streaming?: boolean }) {
  const { spec, error } = useMemo(() => parseChartSpec(raw), [raw]);

  if (streaming && !spec) return <ChartSkeleton />;
  if (!spec) return <ChartError message={error ?? "invalid chart"} raw={raw} />;
  return <Chart spec={spec} />;
}

export function ChartSkeleton() {
  return (
    <div className="my-3 flex h-[180px] animate-pulse items-center justify-center gap-2 rounded-xl border border-border bg-surface-2/50 text-xs text-fg-faint">
      <LineChartIcon size={14} /> chart incoming…
    </div>
  );
}

function ChartError({ message, raw }: { message: string; raw: string }) {
  return (
    <div className="my-3 rounded-xl border border-warn/40 bg-warn-soft/50 p-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-warn">
        <AlertTriangle size={13} /> Could not render this chart: {message}
      </p>
      <pre className="mt-2 max-h-32 overflow-auto rounded bg-surface p-2 font-mono text-[10px] text-fg-muted">{raw}</pre>
    </div>
  );
}

interface Hover {
  x: number;
  y: number;
  label: string;
  rows: Array<{ name: string; color: string; value: number }>;
}

export function Chart({ spec, height }: { spec: ChartSpec; height?: number }) {
  const scales = useMemo(() => buildScales(spec), [spec]);
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const kind: XKind = spec.x?.kind ?? "category";
  const multi = spec.series.length > 1;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * PLOT.width;
    // Nearest category by x position.
    let best: { key: string; dist: number } | null = null;
    for (const key of scales.categories) {
      const dist = Math.abs(scales.xOf(key) - px);
      if (!best || dist < best.dist) best = { key, dist };
    }
    if (!best || best.dist > 60) {
      setHover(null);
      return;
    }
    const rows = spec.series
      .map((s, i) => {
        const point = s.data.find(([x]) => String(x) === best!.key);
        const value = point?.[1];
        return value === null || value === undefined
          ? null
          : { name: s.name, color: SERIES_COLORS[i % SERIES_COLORS.length], value };
      })
      .filter((r): r is NonNullable<typeof r> => r !== null);
    if (rows.length === 0) {
      setHover(null);
      return;
    }
    setHover({ x: scales.xOf(best.key), y: PLOT.top, label: formatX(best.key, kind), rows });
  };

  const stackOffsets = new Map<string, number>();

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-border bg-surface">
      {spec.title && (
        <div className="border-b border-border px-4 py-2">
          <p className="text-xs font-semibold text-fg">{spec.title}</p>
        </div>
      )}
      <div className="relative overflow-x-auto p-2">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${PLOT.width} ${height ?? PLOT.height}`}
          className="w-full"
          style={{ minWidth: 420 }}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          {/* grid + y axis */}
          {scales.yTicks.map((t, i) => (
            <g key={i}>
              <line
                x1={PLOT.left}
                x2={PLOT.width - PLOT.right}
                y1={t.pos}
                y2={t.pos}
                stroke="var(--border)"
                strokeWidth="1"
              />
              <text x={PLOT.left - 8} y={t.pos + 3} textAnchor="end" fontSize="9" fill="var(--fg-faint)">
                {t.label}
              </text>
            </g>
          ))}
          {/* x axis labels */}
          {scales.xTicks.map((t, i) => (
            <text
              key={i}
              x={t.pos}
              y={PLOT.height - PLOT.bottom + 15}
              textAnchor="middle"
              fontSize="9"
              fill="var(--fg-faint)"
            >
              {t.label}
            </text>
          ))}
          {spec.y?.label && (
            <text
              x={-(PLOT.top + (PLOT.height - PLOT.top - PLOT.bottom) / 2)}
              y={12}
              transform="rotate(-90)"
              textAnchor="middle"
              fontSize="9"
              fill="var(--fg-muted)"
            >
              {spec.y.label}
              {spec.y.unit ? ` (${spec.y.unit})` : ""}
            </text>
          )}

          {/* series */}
          {spec.series.map((s, i) => {
            const color = SERIES_COLORS[i % SERIES_COLORS.length];
            if (spec.type === "bar") {
              const barW = Math.max(2, (scales.bandWidth / (spec.stacked ? 1 : spec.series.length)) * 0.7);
              return (
                <g key={i}>
                  {s.data.map(([x, y], j) => {
                    if (y === null) return null;
                    const base = scales.yOf(0);
                    let yPos = scales.yOf(y);
                    let barH = Math.abs(base - yPos);
                    if (spec.stacked) {
                      const prev = stackOffsets.get(String(x)) ?? 0;
                      const top = scales.yOf(prev + y);
                      barH = Math.abs(scales.yOf(prev) - top);
                      yPos = top;
                      stackOffsets.set(String(x), prev + y);
                    }
                    const center = scales.xOf(x);
                    const offset = spec.stacked ? 0 : (i - (spec.series.length - 1) / 2) * barW;
                    return (
                      <rect
                        key={j}
                        x={center + offset - barW / 2}
                        y={Math.min(yPos, base)}
                        width={barW}
                        height={Math.max(barH, 1)}
                        fill={color}
                        opacity="0.85"
                        rx="1.5"
                      />
                    );
                  })}
                </g>
              );
            }
            if (spec.type === "scatter") {
              return (
                <g key={i}>
                  {s.data.map(([x, y], j) =>
                    y === null ? null : <circle key={j} cx={scales.xOf(x)} cy={scales.yOf(y)} r="2.5" fill={color} opacity="0.8" />,
                  )}
                </g>
              );
            }
            return (
              <g key={i}>
                {spec.type === "area" && <path d={areaPath(s.data, scales)} fill={color} opacity="0.14" />}
                <path
                  d={linePath(s.data, scales)}
                  fill="none"
                  stroke={color}
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </g>
            );
          })}

          {/* hover guide */}
          {hover && (
            <line
              x1={hover.x}
              x2={hover.x}
              y1={PLOT.top}
              y2={PLOT.height - PLOT.bottom}
              stroke="var(--fg-faint)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
          )}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 rounded-lg border border-border bg-surface px-2.5 py-1.5 shadow-pop"
            style={{
              left: `min(${(hover.x / PLOT.width) * 100}%, calc(100% - 140px))`,
              top: 8,
            }}
          >
            <p className="mb-0.5 font-mono text-[10px] text-fg-muted">{hover.label}</p>
            {hover.rows.map((r) => (
              <p key={r.name} className="flex items-center gap-1.5 text-[11px] text-fg">
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: r.color }} />
                {multi && <span className="text-fg-muted">{r.name}</span>}
                <span className="font-mono font-medium">{r.value}</span>
                {spec.y?.unit && <span className="text-fg-faint">{spec.y.unit}</span>}
              </p>
            ))}
          </div>
        )}
      </div>

      {multi && (
        <div className="flex flex-wrap gap-3 border-t border-border px-4 py-2">
          {spec.series.map((s, i) => (
            <span key={i} className={cx("flex items-center gap-1.5 text-[11px] text-fg-muted")}>
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
