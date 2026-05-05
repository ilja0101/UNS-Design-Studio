/**
 * Pure math/layout helpers for the visualization canvas.
 *
 * UMD-ish: exposes window.VizMath in the browser AND module.exports for Node.
 * No DOM access, no globals — safe to unit-test with node:test.
 */
(function (global, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    global.VizMath = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  function widgetSize(widget) {
    switch (widget) {
      case 'gauge':   return { w: 70, h: 60 };
      case 'bar':     return { w: 90, h: 48 };
      case 'led':     return { w: 50, h: 32 };
      case 'fill':    return { w: 36, h: 56 };
      case 'numeric':
      default:        return { w: 80, h: 32 };
    }
  }

  function clamp01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

  function fmtNum(v, decimals) {
    if (typeof v !== 'number' || !Number.isFinite(v)) return String(v);
    return v.toFixed(decimals || 0);
  }

  /**
   * Place a gauge near its parent node:
   *  - if explicit layout → use it
   *  - else stack siblings (same entity, no explicit layout) vertically
   *    to the right of the node, centered on node.y.
   */
  function gaugePosition(g, gNodeMap, allGauges) {
    if (g.layout && Number.isFinite(g.layout.x) && Number.isFinite(g.layout.y)) {
      return { x: g.layout.x, y: g.layout.y };
    }
    const sz = widgetSize(g.widget);
    const n  = gNodeMap.get(g.entity);
    if (!n) return { x: 20, y: 20 };

    const siblings = (allGauges || []).filter(x =>
      x.entity === g.entity && (!x.layout || !Number.isFinite(x.layout.x))
    );
    const idx = Math.max(0, siblings.indexOf(g));
    const gap = 6;

    let totalH = 0;
    for (const s of siblings) totalH += widgetSize(s.widget).h + gap;
    totalH -= gap;
    let yOff = -totalH / 2;
    for (let i = 0; i < idx; i++) yOff += widgetSize(siblings[i].widget).h + gap;
    return { x: n.x + n.width / 2 + 12, y: n.y + yOff };
  }

  /**
   * Endpoints of a semicircle arc dome (opens upward) on screen.
   * frac is the filled portion ∈ [0,1].
   * Returns {x0,y0,x1,y1}; (x0,y0)=left baseline, (x1,y1)=tip.
   */
  function arcEndpoints(cx, cy, r, frac) {
    const a0 = Math.PI;
    const a1 = a0 - Math.PI * Math.max(0.0001, frac);
    return {
      x0: cx + r * Math.cos(a0),
      y0: cy - r * Math.sin(a0),
      x1: cx + r * Math.cos(a1),
      y1: cy - r * Math.sin(a1),
    };
  }

  /**
   * Bounding box for a set of dagre-positioned nodes plus gauges.
   * nodes: iterable of { x, y, width, height }.
   * gauges + getPos(g) → {x,y} (top-left of widget rect).
   * Returns { minX, minY, maxX, maxY, w, h } with default min size 400×300.
   */
  function computeBbox(nodes, gauges, getPos) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      minX = Math.min(minX, n.x - n.width  / 2 - 30);
      minY = Math.min(minY, n.y - n.height / 2 - 30);
      maxX = Math.max(maxX, n.x + n.width  / 2 + 30);
      maxY = Math.max(maxY, n.y + n.height / 2 + 30);
    }
    for (const gg of (gauges || [])) {
      const sz  = widgetSize(gg.widget);
      const pos = getPos(gg);
      if (!pos) continue;
      minX = Math.min(minX, pos.x - 12);
      minY = Math.min(minY, pos.y - 12);
      maxX = Math.max(maxX, pos.x + sz.w + 12);
      maxY = Math.max(maxY, pos.y + sz.h + 12);
    }
    if (!Number.isFinite(minX)) { minX = 0; minY = 0; maxX = 400; maxY = 300; }
    const w = Math.max(400, maxX - minX);
    const h = Math.max(300, maxY - minY);
    return { minX, minY, maxX, maxY, w, h };
  }

  /**
   * Map an LED gauge value to its visual fill/stroke pair.
   * null/undefined → "no data" (surface3 + border).
   * Truthy (excluding 'False' / 0) → green; else red.
   */
  function ledColors(value) {
    if (value === null || value === undefined) {
      return { fill: 'var(--surface3)', stroke: 'var(--border)' };
    }
    const on = !!value && value !== 'False' && value !== 0;
    return on
      ? { fill: 'var(--green)', stroke: 'var(--green)' }
      : { fill: 'var(--red)',   stroke: 'var(--red)' };
  }

  /**
   * Filled fraction of a gauge for a given value, min, max ∈ [0,1].
   */
  function gaugeFraction(value, min, max) {
    if (value === null || value === undefined) return 0;
    const v = Number(value);
    if (!Number.isFinite(v)) return 0;
    return clamp01((v - min) / Math.max(0.0001, max - min));
  }

  return {
    widgetSize,
    clamp01,
    fmtNum,
    gaugePosition,
    arcEndpoints,
    computeBbox,
    ledColors,
    gaugeFraction,
  };
});
