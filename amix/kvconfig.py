"""App-side watcher for the ``amix_app_config`` JetStream KV bucket
(amix-standards/APP-GOVERNANCE.md §3).

Python port of `amix-standards/snippets/amixconfig.go`, using nats-py's JetStream
KeyValue API. In governed mode the portal writes the whole platform-config
document for this app's key; the app watches its key and converges — configuration
is a document, not a stream of RPCs, so an app that was offline catches up to the
latest state without replaying history.

``apply`` maps the neutral document onto the app's running config (reusing
whatever live-reconfig path the app's settings-save already uses). ``last_rev``
feeds the ``config_rev`` field of $PLAT health so the portal shows
drift/convergence. Like the Go version it re-reads the live connection each
iteration and rebinds with backoff, so it survives broker restarts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from nats.js.kv import KV_DEL, KV_PURGE

log = logging.getLogger(__name__)

BUCKET = "amix_app_config"

ConnFunc = Callable[[], Any]
# apply(doc_bytes) converges the document onto the app; raising rejects a bad
# document (the watcher keeps the last good rev and retries on the next update).
ApplyFunc = Callable[[bytes], Awaitable[None]]


class Watcher:
    """Watches one app's key in ``amix_app_config`` and converges on each update."""

    def __init__(self, conn: ConnFunc, app_id: str, apply: ApplyFunc, domain: str = "") -> None:
        self._conn = conn
        self._id = app_id
        self._apply = apply
        self._rev = 0
        # JetStream domain of the amix_app_config bucket. Empty = the connection's
        # own domain (all-in-one); set to the hub's domain (e.g. "idmz") so a
        # governed app at L3 reads the bucket across the leaf.
        self._domain = domain

    @property
    def last_rev(self) -> int:
        """The KV revision the app has converged to — echo as ``config_rev``."""
        return self._rev

    async def run(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                await self._watch_once(stop)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — bucket absent / uplink drop: retry
                if stop.is_set():
                    return
                log.debug("amix config watch error (%s); retry in %.0fs", exc, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    async def _watch_once(self, stop: asyncio.Event) -> None:
        nc = self._conn()
        if nc is None or not getattr(nc, "is_connected", False):
            raise ConnectionError("governance NATS not connected")
        js = nc.jetstream(domain=self._domain) if self._domain else nc.jetstream()
        kv = await js.key_value(BUCKET)  # raises if the bucket isn't created yet — caller retries
        watcher = await kv.watch(self._id)
        try:
            while not stop.is_set():
                try:
                    entry = await watcher.updates(timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # no update this tick; loop so we notice stop
                # A None update marks the end of the initial replay (caught up).
                if entry is None:
                    continue
                if entry.operation in (KV_DEL, KV_PURGE):
                    continue  # deletion = no governed config; keep current
                try:
                    await self._apply(entry.value or b"")
                except Exception as exc:  # noqa: BLE001 — reject bad doc; keep last good rev
                    log.warning("amix config: rejected rev %s: %s", entry.revision, exc)
                    continue
                self._rev = int(entry.revision or 0)
        finally:
            try:
                await watcher.stop()
            except Exception:  # noqa: BLE001
                pass
