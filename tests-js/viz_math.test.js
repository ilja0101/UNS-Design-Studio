/**
 * Unit tests for static/js/viz_math.js — pure helpers used by the visualization.
 * Runner: built-in node:test (no deps). Run with `npm test`.
 */
const { test } = require('node:test');
const assert   = require('node:assert/strict');

const VM = require('../static/js/viz_math.js');

// ── widgetSize ──────────────────────────────────────────────────────────────
test('widgetSize returns expected dims for each widget', () => {
  assert.deepEqual(VM.widgetSize('gauge'),   { w: 70, h: 60 });
  assert.deepEqual(VM.widgetSize('bar'),     { w: 90, h: 48 });
  assert.deepEqual(VM.widgetSize('led'),     { w: 50, h: 32 });
  assert.deepEqual(VM.widgetSize('fill'),    { w: 36, h: 56 });
  assert.deepEqual(VM.widgetSize('numeric'), { w: 80, h: 32 });
});

test('widgetSize falls back to numeric for unknown widget', () => {
  assert.deepEqual(VM.widgetSize('mystery'), { w: 80, h: 32 });
  assert.deepEqual(VM.widgetSize(undefined), { w: 80, h: 32 });
});

// ── clamp01 ─────────────────────────────────────────────────────────────────
test('clamp01 clamps to [0,1]', () => {
  assert.equal(VM.clamp01(-5), 0);
  assert.equal(VM.clamp01(0),  0);
  assert.equal(VM.clamp01(0.5), 0.5);
  assert.equal(VM.clamp01(1), 1);
  assert.equal(VM.clamp01(99), 1);
});

// ── fmtNum ──────────────────────────────────────────────────────────────────
test('fmtNum formats finite numbers with decimals', () => {
  assert.equal(VM.fmtNum(3.14159, 2), '3.14');
  assert.equal(VM.fmtNum(42, 0), '42');
  assert.equal(VM.fmtNum(0.5, 1), '0.5');
});

test('fmtNum defaults decimals to 0', () => {
  assert.equal(VM.fmtNum(1.999, undefined), '2');
  assert.equal(VM.fmtNum(1.999, 0), '2');
});

test('fmtNum returns String(v) for non-finite', () => {
  assert.equal(VM.fmtNum(NaN, 1), 'NaN');
  assert.equal(VM.fmtNum(Infinity, 1), 'Infinity');
  assert.equal(VM.fmtNum('abc', 1), 'abc');
  assert.equal(VM.fmtNum(null, 1), 'null');
});

// ── gaugePosition ───────────────────────────────────────────────────────────
test('gaugePosition uses explicit layout when present', () => {
  const g = { entity: 'e1', widget: 'numeric', layout: { x: 100, y: 200 } };
  const map = new Map([['e1', { x: 0, y: 0, width: 100, height: 60 }]]);
  assert.deepEqual(VM.gaugePosition(g, map, [g]), { x: 100, y: 200 });
});

test('gaugePosition single-sibling places to the right of node, centered', () => {
  const g = { entity: 'e1', widget: 'numeric' }; // h = 32
  const node = { x: 100, y: 200, width: 100, height: 60 };
  const map = new Map([['e1', node]]);
  const p = VM.gaugePosition(g, map, [g]);
  assert.equal(p.x, 100 + 50 + 12);    // node.x + width/2 + 12
  assert.equal(p.y, 200 - 16);          // node.y - h/2 (widget top)
});

test('gaugePosition stacks multiple siblings vertically', () => {
  const a = { entity: 'e1', widget: 'numeric' }; // h=32
  const b = { entity: 'e1', widget: 'numeric' };
  const c = { entity: 'e1', widget: 'numeric' };
  const node = { x: 0, y: 0, width: 100, height: 60 };
  const map = new Map([['e1', node]]);
  const all = [a, b, c];
  const pa = VM.gaugePosition(a, map, all);
  const pb = VM.gaugePosition(b, map, all);
  const pc = VM.gaugePosition(c, map, all);
  // 3 widgets of height 32 with gap 6 → total 32*3 + 6*2 = 108 → first y = -54
  assert.equal(pa.y, -54);
  assert.equal(pb.y, -54 + 32 + 6);
  assert.equal(pc.y, -54 + 2 * (32 + 6));
  // all share same x
  assert.equal(pa.x, pb.x);
  assert.equal(pb.x, pc.x);
});

test('gaugePosition skips siblings that have explicit layout', () => {
  const a = { entity: 'e1', widget: 'numeric' }; // h=32
  const b = { entity: 'e1', widget: 'numeric', layout: { x: 999, y: 999 } };
  const node = { x: 0, y: 0, width: 100, height: 60 };
  const map = new Map([['e1', node]]);
  // a is the only sibling without explicit layout → centered around node.y
  const pa = VM.gaugePosition(a, map, [a, b]);
  assert.equal(pa.y, -16); // node.y - h/2
});

test('gaugePosition fallback when entity is unmapped', () => {
  const g = { entity: 'missing', widget: 'numeric' };
  const map = new Map();
  assert.deepEqual(VM.gaugePosition(g, map, [g]), { x: 20, y: 20 });
});

// ── arcEndpoints ────────────────────────────────────────────────────────────
test('arcEndpoints with frac≈0 produces start point ≈ end point at left baseline', () => {
  const e = VM.arcEndpoints(50, 50, 20, 0);
  assert.equal(Math.round(e.x0), 30); // cx - r
  assert.equal(Math.round(e.y0), 50);
  // tip ≈ very close to baseline because frac clamped to 0.0001
  assert.ok(Math.abs(e.x1 - 30) < 0.1);
  assert.ok(Math.abs(e.y1 - 50) < 0.1);
});

test('arcEndpoints with frac=1 spans full semicircle (left → right baseline)', () => {
  const e = VM.arcEndpoints(50, 50, 20, 1);
  assert.equal(Math.round(e.x0), 30); // left
  assert.equal(Math.round(e.y0), 50);
  assert.equal(Math.round(e.x1), 70); // right
  assert.equal(Math.round(e.y1), 50);
});

test('arcEndpoints with frac=0.5 ends at the dome top (cx, cy-r)', () => {
  const e = VM.arcEndpoints(50, 50, 20, 0.5);
  assert.equal(Math.round(e.x1), 50); // cx
  assert.equal(Math.round(e.y1), 30); // cy - r (above baseline on screen)
});

test('arcEndpoints y0 always at baseline (sin(π)=0)', () => {
  for (const frac of [0, 0.25, 0.5, 0.75, 1]) {
    const e = VM.arcEndpoints(100, 100, 30, frac);
    assert.ok(Math.abs(e.y0 - 100) < 0.0001, `frac=${frac} y0=${e.y0}`);
  }
});

// ── computeBbox ─────────────────────────────────────────────────────────────
test('computeBbox covers nodes with 30px padding and clamps to min 400x300', () => {
  const nodes = [{ x: 100, y: 100, width: 100, height: 60 }];
  const bb = VM.computeBbox(nodes, [], () => null);
  assert.equal(bb.minX, 100 - 50 - 30);
  assert.equal(bb.maxX, 100 + 50 + 30);
  assert.equal(bb.w, 400);  // min clamp
  assert.equal(bb.h, 300);
});

test('computeBbox stretches to include far gauge', () => {
  const nodes = [{ x: 0, y: 0, width: 100, height: 60 }];
  const gauges = [{ widget: 'numeric' }]; // 80x32
  const getPos = () => ({ x: 1000, y: 0 });
  const bb = VM.computeBbox(nodes, gauges, getPos);
  // gauge right edge = 1000 + 80 + 12 = 1092
  assert.equal(bb.maxX, 1092);
});

test('computeBbox returns sane defaults when no nodes', () => {
  const bb = VM.computeBbox([], [], () => null);
  assert.equal(bb.minX, 0);
  assert.equal(bb.w, 400);
  assert.equal(bb.h, 300);
});

// ── ledColors ───────────────────────────────────────────────────────────────
test('ledColors null → no-data state', () => {
  assert.deepEqual(VM.ledColors(null),
    { fill: 'var(--surface3)', stroke: 'var(--border)' });
  assert.deepEqual(VM.ledColors(undefined),
    { fill: 'var(--surface3)', stroke: 'var(--border)' });
});

test('ledColors true / 1 / "True" → green', () => {
  for (const v of [true, 1, 'True']) {
    assert.deepEqual(VM.ledColors(v),
      { fill: 'var(--green)', stroke: 'var(--green)' });
  }
});

test('ledColors false / 0 / "False" → red', () => {
  for (const v of [false, 0, 'False']) {
    assert.deepEqual(VM.ledColors(v),
      { fill: 'var(--red)', stroke: 'var(--red)' });
  }
});

// ── gaugeFraction ───────────────────────────────────────────────────────────
test('gaugeFraction maps value within range to [0,1]', () => {
  assert.equal(VM.gaugeFraction(50, 0, 100), 0.5);
  assert.equal(VM.gaugeFraction(0, 0, 100),  0);
  assert.equal(VM.gaugeFraction(100, 0, 100), 1);
});

test('gaugeFraction clamps out-of-range', () => {
  assert.equal(VM.gaugeFraction(-50, 0, 100), 0);
  assert.equal(VM.gaugeFraction(200, 0, 100), 1);
});

test('gaugeFraction handles null/non-numeric', () => {
  assert.equal(VM.gaugeFraction(null, 0, 100), 0);
  assert.equal(VM.gaugeFraction(undefined, 0, 100), 0);
  assert.equal(VM.gaugeFraction('abc', 0, 100), 0);
});

test('gaugeFraction protects against zero-width range', () => {
  // max = min → divisor clamped to 0.0001 → very large positive deviation → clamped to 1
  assert.equal(VM.gaugeFraction(5, 5, 5), 0);
  assert.equal(VM.gaugeFraction(6, 5, 5), 1);
});
