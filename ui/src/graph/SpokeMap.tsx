import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
  type WheelEvent,
} from "react";
import {
  Boxes,
  Building2,
  Cog,
  Cpu,
  Factory,
  LayoutGrid,
  Maximize2,
  Network,
  Package,
  Server,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useGraph } from "./useGraph";
import { computeLayout, type Placed } from "./layout";
import { NodePanel } from "./NodePanel";
import { Toolbar } from "./Toolbar";
import { LiveTree } from "./LiveTree";
import { mergeAssetIntoConfig } from "./unsConfig";
import { api } from "../api";
import type { AssetTemplate, GraphNode, NodeType } from "../types/graph";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// World-space viewport the pan/zoom math works in (mirrors Command-Center's map).
const MAP_W = 1200;
const MAP_H = 760;

// Disc radius per node kind. The core is drawn a touch larger again below.
const NODE_R: Record<NodeType, number> = {
  enterprise: 40,
  businessUnit: 32,
  site: 27,
  area: 23,
  workCenter: 20,
  workUnit: 18,
  system: 26,
};

const ICON: Record<NodeType, typeof Network> = {
  enterprise: Building2,
  businessUnit: Boxes,
  site: Factory,
  area: LayoutGrid,
  workCenter: Cog,
  workUnit: Package,
  system: Server,
};

interface View {
  scale: number;
  tx: number;
  ty: number;
}

function fitView(placed: Placed[], radiusOf: (p: Placed) => number, W: number, H: number): View {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of placed) {
    const r = radiusOf(p);
    minX = Math.min(minX, p.x - r);
    maxX = Math.max(maxX, p.x + r);
    minY = Math.min(minY, p.y - r);
    maxY = Math.max(maxY, p.y + r + 30); // label sits below the disc
  }
  if (!isFinite(minX)) return { scale: 1, tx: 0, ty: 0 };
  const pad = 80;
  const cw = maxX - minX + pad * 2;
  const ch = maxY - minY + pad * 2;
  const scale = Math.max(0.35, Math.min(1.8, Math.min(W / cw, H / ch)));
  return { scale, tx: (minX + maxX) / 2, ty: (minY + maxY) / 2 };
}

export function SpokeMap() {
  const g = useGraph();
  const graph = g.graph;

  const layout = useMemo(
    () => (graph ? computeLayout(graph, g.expanded) : null),
    [graph, g.expanded],
  );

  const radiusOf = (p: Placed) =>
    (p.node.id === layout?.rootId ? 46 : NODE_R[p.node.type] ?? 20);

  const byId = useMemo(() => {
    const m = new Map<string, Placed>();
    if (layout) for (const p of layout.placed) m.set(p.node.id, p);
    return m;
  }, [layout]);

  const [hovered, setHovered] = useState<string | null>(null);

  // viewBox pan/zoom.
  const [view, setView] = useState<View>({ scale: 1, tx: 0, ty: 0 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const rafRef = useRef<number | null>(null);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const reduceMotion =
    typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const animateView = (target: View) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    const start = viewRef.current;
    const t0 = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / 320);
      const e = ease(p);
      setView({
        scale: start.scale + (target.scale - start.scale) * e,
        tx: start.tx + (target.tx - start.tx) * e,
        ty: start.ty + (target.ty - start.ty) * e,
      });
      rafRef.current = p < 1 ? requestAnimationFrame(tick) : null;
    };
    rafRef.current = requestAnimationFrame(tick);
  };
  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); }, []);

  // Refit only when the visible node set changes (expand/collapse, topology) —
  // never on the 2 s stat refetch, so a user's pan/zoom is never yanked away.
  const fitSig = layout ? layout.placed.map((p) => p.node.id).sort().join(",") : "";
  useEffect(() => {
    if (layout && layout.placed.length) animateView(fitView(layout.placed, radiusOf, MAP_W, MAP_H));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitSig]);

  const safeScale = view.scale > 0 && Number.isFinite(view.scale) ? view.scale : 1;
  const safeTx = Number.isFinite(view.tx) ? view.tx : 0;
  const safeTy = Number.isFinite(view.ty) ? view.ty : 0;
  const vw = MAP_W / safeScale;
  const vh = MAP_H / safeScale;
  const viewBox = `${-vw / 2 + safeTx} ${-vh / 2 + safeTy} ${vw} ${vh}`;

  const clampScale = (s: number) => Math.min(2.5, Math.max(0.35, s));
  const fit = () => layout && animateView(fitView(layout.placed, radiusOf, MAP_W, MAP_H));
  const zoomButton = (factor: number) =>
    animateView({ ...viewRef.current, scale: clampScale(viewRef.current.scale * factor) });

  const onWheel = (e: WheelEvent<SVGSVGElement>) => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    setView((v) => ({ ...v, scale: clampScale(v.scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12)) }));
  };
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!drag.current || !svgRef.current) return;
    // Guard a detached / zero-size ref: dividing by a 0-width client rect yields
    // Infinity → a NaN viewBox → a blank white canvas. Compute the geometry
    // outside the setView updater so a bad frame simply no-ops.
    const clientW = svgRef.current.clientWidth;
    if (!clientW || view.scale <= 0) return;
    const dxPx = e.clientX - drag.current.x;
    const dyPx = e.clientY - drag.current.y;
    if (Math.abs(dxPx) + Math.abs(dyPx) > 3) drag.current.moved = true;
    const worldPerPx = (MAP_W / view.scale) / clientW;
    const nextTx = drag.current.tx - dxPx * worldPerPx;
    const nextTy = drag.current.ty - dyPx * worldPerPx;
    if (!Number.isFinite(nextTx) || !Number.isFinite(nextTy)) return;
    setView((v) => ({ ...v, tx: nextTx, ty: nextTy }));
  };
  const onPointerUp = () => (drag.current = null);

  const onAddAsset = async (path: string, asset: AssetTemplate) => {
    const cfg = await api.uns();
    g.saveUns.mutate(mergeAssetIntoConfig(cfg, path, asset));
  };

  const busy =
    g.setLive.isPending || g.resetLive.isPending || g.saveUns.isPending ||
    g.simulation.isPending || g.server.isPending || g.bridge.isPending;

  // Hover trace: dim everything not adjacent to the hovered node.
  const neighbours = new Set<string>();
  if (hovered && layout) {
    neighbours.add(hovered);
    for (const e of layout.edges) {
      if (e.source === hovered) neighbours.add(e.target);
      if (e.target === hovered) neighbours.add(e.source);
    }
  }
  const dimmed = (id: string) => hovered != null && !neighbours.has(id);
  const edgeActive = (s: string, t: string) => hovered != null && (s === hovered || t === hovered);

  // Clicking a node only *selects* it — expansion is controlled separately via
  // the ± badge, so you can click through and inspect nodes while leaving any
  // branches you've opened exactly as they are. Clicking the core collapses all
  // (a quick reset).
  const clickNode = (n: GraphNode) => {
    if (n.id === layout?.rootId) {
      g.collapseAll();
      g.setSelectedId(null);
      return;
    }
    g.setSelectedId(n.id);
  };

  return (
    <div className="relative h-full w-full">
      <Toolbar
        graph={graph}
        onSimulation={(on) => g.simulation.mutate(on)}
        onAllLive={() => g.resetLive.mutate("all")}
        onClear={() => g.resetLive.mutate("none")}
        onServer={(on) => g.server.mutate(on)}
        onBridge={(on) => g.bridge.mutate(on)}
        busy={busy}
      />
      <LiveTree nodes={graph?.nodes ?? []} liveCount={(graph?.nodes ?? []).filter((n) => n.live).length} />

      {(g.server.isError || g.bridge.isError) && (
        <div className="rise-in absolute left-1/2 top-4 z-30 -translate-x-1/2 rounded-lg border border-err/40 bg-err-soft px-3 py-1.5 text-[12px] font-medium text-err shadow-pop">
          {(g.server.error as Error)?.message ?? (g.bridge.error as Error)?.message}
        </div>
      )}

      {graph && graph.nodes.length === 0 && (
        <div className="absolute inset-0 grid place-items-center text-center text-fg-muted">
          <div>
            <p className="text-sm font-medium">No UNS modelled yet.</p>
            <p className="mt-1 text-xs">
              Open the <a className="text-accent underline" href="/uns">UNS Designer</a> to build one.
            </p>
          </div>
        </div>
      )}

      <svg
        ref={svgRef}
        viewBox={viewBox}
        className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onClick={() => g.setSelectedId(null)}
      >
        <style>{`
          .spoke-flow{animation:spokeFlow 1.5s linear infinite}
          @keyframes spokeFlow{to{stroke-dashoffset:-22}}
          .spoke-body{transform-box:fill-box;transform-origin:center;transition:transform 200ms ease-out}
          .spoke-pulse{transform-box:fill-box;transform-origin:center;animation:spokePulse 1.9s ease-out infinite}
          @keyframes spokePulse{0%{opacity:.4;transform:scale(1)}70%{opacity:0;transform:scale(1.7)}100%{opacity:0;transform:scale(1.7)}}
          @media (prefers-reduced-motion:reduce){.spoke-flow,.spoke-pulse{animation:none}}
        `}</style>
        <defs>
          <pattern id="spoke-dots" width="30" height="30" patternUnits="userSpaceOnUse">
            <circle cx="1.4" cy="1.4" r="1.4" fill="var(--fg-faint)" opacity="0.28" />
          </pattern>
        </defs>
        <rect x={-6000} y={-6000} width={12000} height={12000} fill="url(#spoke-dots)" />

        {/* straight spokes — accent + marching flow when live & publishing */}
        {layout?.edges.map((e) => {
          const a = byId.get(e.source);
          const b = byId.get(e.target);
          if (!a || !b) return null;
          const active = edgeActive(e.source, e.target);
          const faded = hovered != null && !active;
          return (
            <line
              key={e.id}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className={cx("transition-tokens", e.pulse && !faded && "spoke-flow")}
              stroke={active ? "var(--accent)" : e.pulse ? "var(--state-ok)" : "var(--border)"}
              strokeWidth={active ? 2 : e.pulse ? 1.6 : 1.1}
              strokeDasharray={e.pulse ? "5 7" : undefined}
              opacity={faded ? 0.12 : e.pulse ? 0.75 : 0.5}
            />
          );
        })}

        {/* live message particles riding inward toward the core */}
        {!reduceMotion &&
          layout?.edges.map((e) => {
            if (!e.pulse) return null;
            const a = byId.get(e.source);
            const b = byId.get(e.target);
            if (!a || !b) return null;
            if (hovered != null && !edgeActive(e.source, e.target)) return null;
            // flow inward: from the node farther from centre to the nearer one.
            const [s, t] = Math.hypot(a.x, a.y) >= Math.hypot(b.x, b.y) ? [a, b] : [b, a];
            const len = Math.hypot(t.x - s.x, t.y - s.y) || 1;
            const dur = Math.max(1.1, len / 150);
            return (
              <circle key={`flow-${e.id}`} r={2.6} fill="var(--state-ok)">
                <animateMotion
                  dur={`${dur.toFixed(2)}s`}
                  repeatCount="indefinite"
                  path={`M ${s.x} ${s.y} L ${t.x} ${t.y}`}
                />
              </circle>
            );
          })}

        {/* nodes */}
        {layout?.placed.map((p) => (
          <MapNode
            key={p.node.id}
            placed={p}
            r={radiusOf(p)}
            isCore={p.node.id === layout.rootId}
            expandable={g.hasChildren(p.node.id)}
            expanded={g.expanded.has(p.node.id)}
            dim={dimmed(p.node.id)}
            active={hovered === p.node.id}
            selected={p.node.id === g.selectedId}
            onHover={(h) => setHovered(h ? p.node.id : null)}
            onClick={() => {
              if (drag.current?.moved) return;
              clickNode(p.node);
            }}
            onToggle={() => {
              if (drag.current?.moved) return;
              g.toggleExpand(p.node.id);
            }}
          />
        ))}
      </svg>

      {g.selected && (
        <NodePanel
          node={g.selected}
          allNodes={graph?.nodes ?? []}
          onSetLive={(pth, live) => g.setLive.mutate({ path: pth, live })}
          onAddAsset={onAddAsset}
          onClose={() => g.setSelectedId(null)}
          busy={busy}
        />
      )}

      {/* legend */}
      <div className="pointer-events-none absolute bottom-3 left-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-fg-muted">
        <LegendItem swatch={<Network size={12} className="text-accent" />} label="UNS core" />
        <LegendItem swatch={<Factory size={12} className="text-fg-muted" />} label="OT node" />
        <LegendItem swatch={<Server size={12} className="text-fg-muted" />} label="IT system" />
        <LegendItem swatch={<span className="h-[2px] w-4 bg-ok" />} label="publishing" />
        <LegendItem swatch={<span className="h-1.5 w-1.5 rounded-full bg-ok" />} label="live messages" />
        <LegendItem swatch={<span className="h-[2px] w-4 bg-border" />} label="not live" />
      </div>

      {/* zoom / fit controls */}
      <div className="absolute bottom-3 right-3 flex flex-col gap-1">
        <CtrlBtn title="Zoom in" onClick={() => zoomButton(1.2)}><ZoomIn size={15} /></CtrlBtn>
        <CtrlBtn title="Zoom out" onClick={() => zoomButton(1 / 1.2)}><ZoomOut size={15} /></CtrlBtn>
        <CtrlBtn title="Fit to screen" onClick={fit}><Maximize2 size={15} /></CtrlBtn>
      </div>
    </div>
  );
}

function LegendItem({ swatch, label }: { swatch: ReactNode; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      {swatch}
      {label}
    </span>
  );
}

function CtrlBtn({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-surface text-fg-muted shadow-card hover:bg-surface-2 hover:text-fg"
    >
      {children}
    </button>
  );
}

function MapNode({
  placed,
  r,
  isCore,
  expandable,
  expanded,
  dim,
  active,
  selected,
  onHover,
  onClick,
  onToggle,
}: {
  placed: Placed;
  r: number;
  isCore: boolean;
  expandable: boolean;
  expanded: boolean;
  dim: boolean;
  active: boolean;
  selected: boolean;
  onHover: (hovering: boolean) => void;
  onClick: () => void;
  onToggle: () => void;
}) {
  const n = placed.node;
  const Icon = isCore ? Network : n.type === "system" ? Server : ICON[n.type] ?? Cpu;
  const live = n.live;
  const publishing = live && n.running;

  // Family palette: live+publishing → ok, live+idle → accent, offline → muted.
  const ring = selected
    ? "var(--accent)"
    : publishing
      ? "var(--state-ok)"
      : live
        ? "var(--accent)"
        : "var(--border)";
  const fill = isCore
    ? "var(--accent-soft)"
    : publishing
      ? "var(--state-ok-soft)"
      : live
        ? "var(--accent-soft)"
        : "var(--surface-2)";
  const iconColor = isCore
    ? "var(--accent)"
    : publishing
      ? "var(--state-ok)"
      : live
        ? "var(--accent)"
        : "var(--fg-muted)";

  const iconSize = Math.round(r * 0.9);

  return (
    <g
      transform={`translate(${placed.x} ${placed.y})`}
      className="cursor-pointer transition-tokens"
      opacity={dim ? 0.25 : 1}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
    >
      {selected && <circle r={r} fill="none" stroke="var(--accent)" strokeWidth={2} className="spoke-pulse" />}
      <g className="spoke-body" style={{ transform: active ? "scale(1.08)" : "scale(1)" }}>
        <circle
          r={r}
          fill="var(--surface)"
          stroke={ring}
          strokeWidth={selected || isCore ? 2.4 : 1.4}
          strokeDasharray={live ? undefined : "3 3"}
        />
        <circle r={r - 5} fill={fill} />
        <Icon
          x={-iconSize / 2}
          y={-iconSize / 2}
          width={iconSize}
          height={iconSize}
          color={iconColor}
          strokeWidth={1.8}
        />
        {n.tagCount > 0 && (
          <g transform={`translate(${r - 5} ${-r + 5})`}>
            <circle r={9} fill="var(--accent)" />
            <text
              textAnchor="middle"
              dominantBaseline="central"
              className="fill-[var(--accent-fg)] font-semibold"
              style={{ fontSize: 9 }}
            >
              {n.tagCount}
            </text>
          </g>
        )}
        {expandable && (
          <g
            transform={`translate(0 ${r})`}
            className="cursor-pointer"
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
          >
            {/* generous transparent hit area so the toggle is easy to click */}
            <circle cy={0} r={12} fill="transparent" />
            <circle cy={0} r={8} fill="var(--surface)" stroke={expanded ? "var(--accent)" : "var(--border)"} strokeWidth={1.2} />
            <text
              textAnchor="middle"
              dominantBaseline="central"
              className={expanded ? "fill-[var(--accent)] font-bold" : "fill-[var(--fg-muted)] font-bold"}
              style={{ fontSize: 12 }}
            >
              {expanded ? "–" : "+"}
            </text>
          </g>
        )}
      </g>
      <text
        y={r + 18}
        textAnchor="middle"
        stroke="var(--surface)"
        strokeWidth={3.5}
        paintOrder="stroke"
        strokeLinejoin="round"
        className={cx("fill-[var(--fg)] font-semibold", isCore ? "text-[15px]" : "text-[12px]")}
      >
        {n.name}
      </text>
      <text
        y={r + (isCore ? 34 : 31)}
        textAnchor="middle"
        stroke="var(--surface)"
        strokeWidth={3}
        paintOrder="stroke"
        strokeLinejoin="round"
        className={cx(
          "uppercase tracking-wide",
          isCore
            ? "fill-[var(--accent)] text-[11px] font-semibold tracking-[0.18em]"
            : "fill-[var(--fg-faint)] text-[9.5px]",
        )}
      >
        {isCore ? "Unified Name Space" : n.type}
      </text>
    </g>
  );
}
