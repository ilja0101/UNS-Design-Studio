"""AmixRuntime — binds the governance pieces onto one NATS connection.

In governed mode the app opens a single dedicated connection to the AMIX control
leaf (``AMIX_NATS_URL``) and rides two things on it:
  1. ``$PLAT`` announce + health (amix.announce)
  2. the ``amix_app_config`` KV watch (amix.kvconfig)
  (the SSO route lives in the HTTP app, amix.web — not here.)

## Flask-vs-FastAPI note (this app is Quart / async ASGI)

The porting brief assumed Design Studio was a *synchronous* Flask/WSGI app, which
would force this runtime onto a background asyncio loop in a daemon thread. In
fact ``app.py`` is a **Quart** app (async ASGI, `app.run()` → hypercorn) with an
``@app.before_serving`` startup hook and ``async def`` routes — structurally the
same as the FastAPI template. So the correct, simpler adaptation is to run the
runtime on the app's **own** event loop, started from ``before_serving`` and
stopped from ``after_serving`` — exactly like the template's lifespan. A separate
thread + loop would be strictly worse here: the bridge (subprocess transport,
aiomqtt/nats clients) is bound to the app loop, so cross-loop calls from a thread
would be unsafe. This runtime is nonetheless loop-agnostic — ``start`` schedules
its tasks on ``asyncio.get_running_loop()`` — so if Design Studio were ever run
under true WSGI, the same object drops onto a dedicated background-thread loop
unchanged.

Standalone: never constructed (app.py only builds it when governed()).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from amix.announce import Announce, run_announce
from amix.governance import Governance
from amix.kvconfig import Watcher

log = logging.getLogger(__name__)

# apply(doc_bytes) converges an amix_app_config document onto the running app.
ApplyFunc = Callable[[bytes], Awaitable[None]]


class AmixRuntime:
    """Owns the governance NATS connection + the announce/KV-watch tasks."""

    def __init__(self, governance: Governance, announce: Announce, apply: ApplyFunc) -> None:
        self.gov = governance
        self._announce = announce
        self._nc: Any = None
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._watcher = Watcher(lambda: self._nc, governance.app_id, apply)

    @property
    def last_rev(self) -> int:
        return self._watcher.last_rev

    async def start(self) -> None:
        # Non-blocking: connect on a background task (retrying) so a down control
        # leaf never blocks app startup. announce + the KV watcher run immediately
        # and gate on the live connection, so they simply idle until it is up.
        self._stop = asyncio.Event()
        self._tasks.append(asyncio.create_task(self._connect_loop(), name="amix-connect"))
        self._tasks.append(asyncio.create_task(self._watcher.run(self._stop), name="amix-config-watch"))
        self._tasks.append(
            asyncio.create_task(
                run_announce(lambda: self._nc, self._announce, self._health, self._stop),
                name="amix-announce",
            )
        )

    async def _connect_loop(self) -> None:
        """Connect to the AMIX control leaf, retrying until it comes up. Once
        connected, nats-py handles reconnects internally (max_reconnect_attempts=-1),
        so this returns; announce/watcher survive drops via the connection getter."""
        import nats

        opts: dict[str, Any] = {
            "servers": [self.gov.nats_url],
            "name": "uns-design-studio-amix",
            "max_reconnect_attempts": -1,
            "connect_timeout": 5,
        }
        if self.gov.nats_creds:
            opts["user_credentials"] = self.gov.nats_creds
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._nc = await nats.connect(**opts)
                log.info("$PLAT: AMIX governance connected to %s (app id %s)", self.gov.nats_url, self.gov.app_id)
                return
            except Exception as exc:  # noqa: BLE001 — control leaf down: retry, never crash
                log.debug("amix: control leaf connect failed (%s); retry in %.0fs", exc, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    def _health(self) -> tuple[str, dict]:
        # config_rev echoes the amix_app_config revision this app converged to, so
        # the portal shows drift/convergence per app.
        return "ok", {"config_rev": str(self.last_rev)}

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:  # noqa: BLE001
                pass
            self._nc = None
