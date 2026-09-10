"""A short value history for a watch-list of tags, fed by the OPC-UA poll loop.

UDS never kept history: the simulator generates values, the bridge publishes
them, and whoever wants a trend keeps it downstream. The agent changes that
calculus a little -- "is the flow rate actually moving?" is a fair question to
ask the thing that owns the simulation -- so this keeps the last
:data:`MAXLEN` samples of each *watched* tag, in memory, nothing else. The poll
loop in app.py already visits the server every few seconds for the dashboard;
recording a handful of extra reads on the way costs nothing measurable, and a
tag nobody watches costs nothing at all.

Paths are the agent's: ``site/area/unit`` (root name optional) plus a tag
name. They are resolved to the OPC-UA browse path with the same rules the
visualisation page uses (``viz_service.resolve_tag_path``), so a tag the
gauges can read, the trend can read.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

MAXLEN = 600          # samples per tag; at the 3 s poll that is half an hour
MAX_WATCH = 32        # tags on the watch list at once
DEFAULT_POINTS = 120  # what a read returns unless asked otherwise


def key_for(path: str, tag: str) -> str:
    parts = [p for p in str(path or '').replace('\\', '/').split('/') if p.strip()]
    return '/'.join(parts) + ':' + str(tag or '').strip()


class TrendStore:
    """Thread-safe ring buffers keyed by ``path:tag``."""

    def __init__(self, maxlen: int = MAXLEN, max_watch: int = MAX_WATCH):
        self.maxlen = maxlen
        self.max_watch = max_watch
        self._lock = threading.RLock()   # add() describes under the lock
        self._watch: dict[str, dict[str, Any]] = {}
        self._samples: dict[str, deque] = {}

    # ── watch list ──────────────────────────────────────────────────────────

    def add(self, path: str, tag: str, opc_parts: list[str], **meta: Any) -> dict:
        key = key_for(path, tag)
        with self._lock:
            if key not in self._watch and len(self._watch) >= self.max_watch:
                raise ValueError(f'the watch list holds {self.max_watch} tags; remove one first')
            entry = self._watch.get(key) or {'key': key, 'path': path, 'tag': tag,
                                             'since': _now()}
            entry.update({'opc': list(opc_parts), **meta})
            self._watch[key] = entry
            self._samples.setdefault(key, deque(maxlen=self.maxlen))
            return self.describe(key)

    def remove(self, path: str, tag: str) -> bool:
        key = key_for(path, tag)
        with self._lock:
            self._samples.pop(key, None)
            return self._watch.pop(key, None) is not None

    def watched(self) -> list[dict]:
        with self._lock:
            keys = list(self._watch)
        return [self.describe(k) for k in keys]

    def targets(self) -> list[tuple[str, list[str]]]:
        """(key, opc browse path) for the poll loop -- a snapshot, no lock held while reading OPC."""
        with self._lock:
            return [(k, list(e['opc'])) for k, e in self._watch.items()]

    def describe(self, key: str) -> dict:
        with self._lock:
            e = self._watch.get(key)
            if e is None:
                return {}
            samples = self._samples.get(key) or ()
            last = samples[-1] if samples else None
            return {'key': key, 'path': e['path'], 'tag': e['tag'], 'unit': e.get('unit', ''),
                    'since': e['since'], 'samples': len(samples),
                    'last': {'ts': _iso(last[0]), 'value': last[1]} if last else None}

    # ── samples ─────────────────────────────────────────────────────────────

    def record(self, key: str, value: Any, ts: float | None = None) -> None:
        with self._lock:
            buf = self._samples.get(key)
            if buf is not None:
                buf.append((ts if ts is not None else time.time(), value))

    def read(self, path: str, tag: str, seconds: float = 300, points: int = DEFAULT_POINTS) -> dict:
        key = key_for(path, tag)
        with self._lock:
            if key not in self._watch:
                raise KeyError(key)
            e = self._watch[key]
            cutoff = time.time() - max(1.0, float(seconds))
            raw = [(t, v) for t, v in self._samples.get(key, ()) if t >= cutoff]
        numeric = [(t, float(v)) for t, v in raw if _is_number(v)]
        thinned = _thin(numeric, max(2, int(points or DEFAULT_POINTS)))
        values = [v for _, v in numeric]
        out = {
            'key': key, 'path': e['path'], 'tag': e['tag'], 'unit': e.get('unit', ''),
            'seconds': seconds, 'samples': len(raw), 'returned': len(thinned),
            'from': _iso(raw[0][0]) if raw else None, 'to': _iso(raw[-1][0]) if raw else None,
        }
        if values:
            out['stats'] = {'min': min(values), 'max': max(values),
                            'mean': sum(values) / len(values), 'last': values[-1]}
        if raw and not numeric:
            out['note'] = 'values are not numeric; showing the last few as text'
            out['last_values'] = [{'ts': _iso(t), 'value': v} for t, v in raw[-5:]]
        # A chart spec the transcript renders directly from the tool card, so
        # the model never has to repeat the numbers in its answer.
        out['chart'] = {
            'type': 'line', 'title': f"{e['tag']} @ {e['path']}",
            'x': {'kind': 'time'}, 'y': {'label': e['tag'], 'unit': e.get('unit', '')},
            'series': [{'name': e['tag'], 'data': [[_iso(t), v] for t, v in thinned]}],
        }
        return out


def _thin(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[int(i * step)] for i in range(limit)]


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iso(ts: float) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))


def _now() -> str:
    return _iso(time.time())
