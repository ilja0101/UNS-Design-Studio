#!/usr/bin/env python3
"""Give every RoyalFarmersCollective site its own NATS user inside one account.

The seven simulators shared `svc.creds`, which can publish anything. That is
fine for getting bytes onto the mesh and wrong as a design: a simulator for
Heerenveen could publish Terneuzen's subjects and nothing would stop it.

An account is the tenancy boundary and a user is an identity inside it, so the
seven sites of one enterprise belong in one account with a user each, and each
user's publish permission is limited to its own subtree. That is what this
script builds.

Per site it:

  1. creates a user in the account (POST /api/mesh/users)
  2. limits it to its own subtree (PATCH /api/mesh/users/{id}/permissions)
  3. downloads its creds (GET /api/mesh/users/{id}/creds)
  4. writes the file into the mesh volume the simulators already mount
  5. points that simulator's bridge at its own creds and restarts it

It needs an AMIX admin session, because minting a user uses the account signing
seed and setting permissions is admin-only. Pass the login in the environment:

    AMIX_USER=admin AMIX_PASS=... python tools/mint_rfc_site_users.py

Add --dry-run to see the plan without writing anything.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENTERPRISE = "RoyalFarmersCollective"

# port, business unit, plant, container. The account is one for all of them.
SITES = [
    (5001, "FritoMaxx", "Heerenveen", "rfc-sim-heerenveen"),
    (5002, "FritoMaxx", "Hoogeveen", "rfc-sim-hoogeveen"),
    (5003, "KnappertjesBV", "Terneuzen", "rfc-sim-terneuzen"),
    (5004, "DeBietenBende", "Zevenbergen", "rfc-sim-zevenbergen"),
    (5005, "Vlokkenheim", "Emmeloord", "rfc-sim-emmeloord"),
    (5006, "Wortelkracht", "Roosendaal", "rfc-sim-roosendaal"),
    (5007, "GroupServices", "Veghel-HQ", "rfc-sim-veghel"),
]

opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def hub(base: str, path: str, body=None, method: str | None = None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data,
        method=method or ("POST" if body is not None else "GET"),
        headers={"content-type": "application/json"})
    with opener.open(req, timeout=60) as r:
        out = r.read().decode()
    if raw:
        return out
    return json.loads(out or "{}")


def sim(port: int, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        method="POST" if body is not None else "GET",
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default="http://localhost:8430")
    ap.add_argument("--account", type=int, default=2,
                    help="the NATS account every site user is created in")
    ap.add_argument("--volume", default="amix_meshcfg",
                    help="docker volume the simulators mount at /mesh")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    user, password = os.environ.get("AMIX_USER"), os.environ.get("AMIX_PASS")
    if not a.dry_run and not (user and password):
        print("set AMIX_USER and AMIX_PASS", file=sys.stderr)
        return 2

    if not a.dry_run:
        hub(a.hub, "/api/login", {"Username": user, "Password": password})
        print(f"signed in to {a.hub}")

    made = []
    for port, group, plant, container in SITES:
        subtree = f"{ENTERPRISE}.{group}.{plant}.>"
        name = f"rfc-{plant.lower().replace('-', '')}"
        print(f"\n=== {group}|{plant} ===")
        print(f"  user {name} in account {a.account}, may publish {subtree}")
        if a.dry_run:
            continue

        u = hub(a.hub, "/api/mesh/users",
                {"account_id": a.account, "Name": name, "Bearer": False})
        uid = u.get("id") or u.get("ID")
        if not uid:
            print(f"  FAILED to create: {u}")
            continue

        # Publish only its own subtree. Subscribe stays open so the simulator
        # can still be reached for command write-back, which is a separate
        # decision from what it may produce.
        hub(a.hub, f"/api/mesh/users/{uid}/permissions",
            {"pub_allow": [subtree], "pub_deny": [], "sub_allow": [">"],
             "sub_deny": [], "max_subscriptions": 0, "max_payload": 0,
             "bearer_token": False},
            method="PATCH")

        creds = hub(a.hub, f"/api/mesh/users/{uid}/creds", raw=True)
        target = f"/mesh/{name}.creds"
        # Written through a throwaway container because the volume belongs to
        # the mesh, not to this machine's filesystem.
        subprocess.run(
            ["docker", "run", "--rm", "-i", "-v", f"{a.volume}:/mesh",
             "alpine", "sh", "-c", f"cat > {target} && chmod 644 {target}"],
            input=creds.encode(), check=True)
        print(f"  creds -> {target}")

        sim(port, "/api/bridge/config", {"creds": target})
        sim(port, "/api/bridge/stop", {})
        time.sleep(1)
        sim(port, "/api/bridge/start", {})
        made.append((port, f"{group}|{plant}", name))

    if a.dry_run:
        return 0

    print("\nwaiting for the bridges to publish under their own identity…")
    time.sleep(15)
    bad = 0
    for port, label, name in made:
        st = sim(port, "/api/status").get("bridge_stats") or {}
        ok = bool(st.get("published"))
        print(f"  {'publishing' if ok else 'NOT publishing':<15} {label:<28} {name} "
              f"(errors {st.get('errors')})")
        bad += 0 if ok else 1
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
