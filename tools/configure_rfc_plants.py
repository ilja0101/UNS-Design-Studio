#!/usr/bin/env python3
"""Point each RoyalFarmersCollective plant simulator at the AMIX eventMESH.

One container per plant, each publishing only its own site. The steps per
instance are the ones a person would take in the dashboard:

  1. clear live UNS membership, then mark this plant's branch live
  2. start the OPC-UA server, then start the plant itself
  3. configure the bridge for NATS with a credentials file
  4. start the bridge and check it published something

Live membership is what makes each container one plant. Every instance holds
the whole enterprise model, so slicing the model per container would leave
seven copies to keep in step; marking one branch live says the same thing in
one call and survives an edit to the model.

The bridge authenticates with a credentials file because every AMIX broker runs
in operator mode, where username and password are refused.

Usage:
    python tools/configure_rfc_plants.py [--dry-run] [--creds /mesh/svc.creds]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# port -> (business unit, plant). The port is the dashboard published by
# docker-compose.rfc-plants.yml; the pair is the key the simulator uses.
PLANTS: list[tuple[int, str, str]] = [
    (5001, "FritoMaxx", "Heerenveen"),
    (5002, "FritoMaxx", "Hoogeveen"),
    (5003, "KnappertjesBV", "Terneuzen"),
    (5004, "DeBietenBende", "Zevenbergen"),
    (5005, "Vlokkenheim", "Emmeloord"),
    (5006, "Wortelkracht", "Roosendaal"),
    (5007, "GroupServices", "Veghel-HQ"),
]

ENTERPRISE = "RoyalFarmersCollective"

# The enterprise model every instance loads. Shipped in the repo root as the
# default RoyalFarmersCollective import.
MODEL_FILE = "default-uns-rfc-main-import.json"
_here = __file__.rsplit("/", 1)[0].rsplit("\\", 1)[0]
with open(f"{_here}/../{MODEL_FILE}", encoding="utf-8") as _f:
    MODEL = json.load(_f)


def call(port: int, path: str, body: dict | None = None, timeout: float = 60.0,
         ok_status: tuple[int, ...] = ()):
    """POST when a body is given, GET otherwise.

    `ok_status` names HTTP codes to treat as success. `/api/server/start`
    answers 409 when the server is already up, which UDS_AUTOSTART makes the
    normal case rather than a failure.
    """
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if body is not None else "GET",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        if e.code in ok_status:
            return {"ok": True, "status": e.code}
        raise
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def wait_up(port: int, seconds: float = 120.0) -> bool:
    """A fresh container builds its model on first boot, so the dashboard can
    take a while to answer. Waiting is the difference between a flaky script and
    one that works on a cold `up -d`."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            call(port, "/api/status", timeout=5)
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(2)
    return False


def configure(port: int, group: str, plant: str, creds: str, broker: str,
              broker_port: int, interval: float, dry: bool) -> bool:
    label = f"{group}|{plant}"
    branch = f"{ENTERPRISE}|{group}|{plant}"
    print(f"\n=== :{port}  {label} ===", flush=True)

    if dry:
        print(f"  would mark live: {branch}")
        print(f"  would bridge to nats://{broker}:{broker_port} creds {creds}")
        return True

    if not wait_up(port):
        print("  FAILED: dashboard never answered")
        return False

    # 0. A fresh container ships a Vault-Tec demo model, so the enterprise has
    #    to be loaded before any RoyalFarmersCollective path means anything.
    #    Saving the model restarts the factory, and the plant list only changes
    #    once that is back up.
    call(port, "/api/uns", MODEL, timeout=180)
    for _ in range(60):
        st = call(port, "/api/status")
        if any(k.startswith(f"{group}|") for k in (st.get("plants") or {})):
            break
        time.sleep(2)
    else:
        print("  FAILED: the enterprise model never took")
        return False
    print(f"  model: {st.get('enterprise_name')} ({len(st.get('plants') or {})} plants)")

    # 1. Exactly one plant per instance.
    call(port, "/api/uns/live/reset", {"mode": "none"})
    live = call(port, "/api/uns/live", {"path": branch, "live": True,
                                        "include_descendants": True})
    paths = (live.get("live") or {}).get("paths") or []
    print(f"  live branch: {paths}")

    # 2. The OPC-UA server has to be up before a plant can be started, and the
    #    plant start refuses with 409 when it is not. Saving the model above
    #    already restarted it, so 409 here means "already running".
    call(port, "/api/server/start", {}, ok_status=(409,))
    time.sleep(2)
    started = call(port, "/api/plant/control",
                   {"group": group, "plant": plant, "action": "set_state", "value": True})
    print(f"  plant start: {started.get('msg', started)}")

    # 3+4. The bridge. Saving while it runs restarts it, so configure first.
    call(port, "/api/bridge/config", {
        "protocol": "nats",
        "broker_host": broker,
        "broker_port": broker_port,
        "creds": creds,
        "interval": interval,
        "topic_prefix": "",
    })
    call(port, "/api/bridge/start", {})

    # Give it a few poll intervals before judging it. A bridge that has not
    # published yet and a bridge that cannot are different facts.
    deadline = time.time() + max(20.0, interval * 6)
    stats = {}
    while time.time() < deadline:
        st = call(port, "/api/status")
        stats = st.get("bridge_stats") or {}
        if stats.get("published"):
            break
        time.sleep(2)

    ok = bool(stats.get("published"))
    print(f"  bridge: connected={stats.get('connected')} opc_ok={stats.get('opc_ok')} "
          f"published={stats.get('published')} errors={stats.get('errors')}")
    if not ok:
        print("  NOT PUBLISHING yet")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--creds", default="/mesh/svc.creds",
                    help="credentials file path inside the container")
    ap.add_argument("--broker", default="l3", help="broker host on the mesh network")
    ap.add_argument("--broker-port", type=int, default=4222)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    results = []
    for port, group, plant in PLANTS:
        try:
            results.append((f"{group}|{plant}",
                            configure(port, group, plant, a.creds, a.broker,
                                      a.broker_port, a.interval, a.dry_run)))
        except Exception as exc:  # noqa: BLE001 - report and carry on
            print(f"  ERROR: {exc}")
            results.append((f"{group}|{plant}", False))

    print("\n=== summary ===")
    for name, ok in results:
        print(f"  {'publishing' if ok else 'NOT publishing':<15} {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
