"""$PLAT self-registration (amix-standards/PLAT-SUBJECTS.md).

Python port of `UNS-Trendminer/internal/platannounce/announce.go`, adapted from
`amix-standards/snippets/announce.py`. Publishes ``$PLAT.app.announce.<id>`` every
30s and ``$PLAT.app.health.<id>`` every 10s, so the app appears (and is
health-monitored) in the platform portal.

Like the Go version it is decoupled from the NATS client: it pulls the live
connection each tick via a getter, so it survives reconnects with no extra
wiring; a tick with no live connection is simply skipped. Run it in governed mode
ONLY — a standalone deployment publishes nothing to the platform bus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

ANNOUNCE_INTERVAL = 30.0
HEALTH_INTERVAL = 10.0

# conn() returns the live nats client or None if not currently connected.
ConnFunc = Callable[[], Any]
# health() may be sync or async, returns (status, details).
HealthFunc = Callable[[], "tuple[str, dict] | Awaitable[tuple[str, dict]]"]


@dataclass
class Announce:
    id: str
    name: str
    version: str
    category: str  # Core|Connect|Historize|Intelligence|Experience
    layer: str  # l3|l35|l4
    url: str = ""
    icon: str = ""
    description: str = ""
    capabilities: Optional[dict] = field(default=None)


def _connected(nc: Any) -> bool:
    return nc is not None and getattr(nc, "is_connected", False)


async def run_announce(
    conn: ConnFunc,
    a: Announce,
    health: Optional[HealthFunc],
    stop: asyncio.Event,
) -> None:
    """Publish announce + health until ``stop`` is set. Launch as a task."""
    ann_subj = f"$PLAT.app.announce.{a.id}"
    health_subj = f"$PLAT.app.health.{a.id}"
    ann_bytes = json.dumps({k: v for k, v in asdict(a).items() if v not in ("", None)}).encode()

    async def publish_announce() -> None:
        nc = conn()
        if _connected(nc):
            await nc.publish(ann_subj, ann_bytes)

    async def publish_health() -> None:
        nc = conn()
        if not _connected(nc):
            return
        status, details = "ok", None
        if health is not None:
            res = health()
            status, details = await res if asyncio.iscoroutine(res) else res
        await nc.publish(
            health_subj,
            json.dumps({"status": status, "ts_ms": int(time.time() * 1000), "details": details}).encode(),
        )

    async def loop(interval: float, fn: Callable[[], Awaitable[None]]) -> None:
        while not stop.is_set():
            try:
                await fn()
            except Exception as exc:  # noqa: BLE001 — a publish failure never kills the beat
                log.debug("$PLAT publish failed: %s", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # The control-leaf connect happens on a background task, so wait until it is
    # up before the first beat — otherwise the initial publish is dropped and the
    # portal only sees the app a full interval later.
    while not stop.is_set() and not _connected(conn()):
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.2)
        except asyncio.TimeoutError:
            pass
    if stop.is_set():
        return

    # Fire once immediately so the portal sees the app the instant it connects.
    await publish_announce()
    await publish_health()
    await asyncio.gather(
        loop(ANNOUNCE_INTERVAL, publish_announce),
        loop(HEALTH_INTERVAL, publish_health),
    )
