#!/usr/bin/env python3
"""Provision the two-business-group demo mesh: two accounts, one user per site.

The shape, which is Ilja's:

    one NATS account per business group
    one iDMZ cluster per business group
    one NATS user per site

An account is the tenancy boundary and a user is an identity inside it, so the
sites of a group share its account and differ by user. Each user may publish
only its own site's subtree, which is what stops one simulator speaking for
another.

This script does the account and user half, and repoints the simulators. It
creates nothing that already exists, so it is safe to run twice.

The iDMZ cluster per group is a topology change (a second broker, new leaf
configs, the runtimes below it rebound) and is deliberately NOT done here.

    AMIX_USER=admin AMIX_PASS=... python tools/provision_two_groups.py
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

# business group -> (AMIX business group id on the local hub, account name,
#                    [(site, simulator port, container)])
GROUPS = {
    "FritoMaxx": (4, "fritomaxx", [
        ("Heerenveen", 5001, "rfc-sim-heerenveen"),
        ("Hoogeveen", 5002, "rfc-sim-hoogeveen"),
        ("Emmeloord", 5005, "rfc-sim-emmeloord"),
    ]),
    "DeBietenBende": (5, "debietenbende", [
        ("Zevenbergen", 5004, "rfc-sim-zevenbergen"),
        ("Roosendaal", 5006, "rfc-sim-roosendaal"),
        ("Terneuzen", 5003, "rfc-sim-terneuzen"),
    ]),
}

opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def hub(base, path, body=None, method=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method or ("POST" if body is not None else "GET"),
        headers={"content-type": "application/json"})
    with opener.open(req, timeout=90) as r:
        out = r.read().decode()
    return out if raw else json.loads(out or "{}")


def sim(port, path, body=None, timeout=180, ok_status=(409,)):
    """`ok_status` names codes that are not failures. /api/server/start answers
    409 when the OPC server is already up, which UDS_AUTOSTART makes the normal
    case, and saving the model restarts it anyway."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        method="POST" if body is not None else "GET",
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code in ok_status:
            return {"ok": True, "status": e.code}
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default="http://localhost:8430")
    ap.add_argument("--operator", type=int, default=1)
    ap.add_argument("--volume", default="amix_meshcfg")
    ap.add_argument("--model", default=None, help="two-group model to load into each simulator")
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    model_path = a.model or os.path.join(here, "..", "uns-rfc-two-groups.json")
    with open(model_path, encoding="utf-8") as f:
        model = json.load(f)

    hub(a.hub, "/api/login", {"Username": os.environ["AMIX_USER"],
                              "Password": os.environ["AMIX_PASS"]})
    print(f"signed in to {a.hub}")

    existing_acc = {a_["name"]: a_["id"] for op in hub(a.hub, "/api/mesh/tree")
                    for a_ in (op.get("accounts") or [])}
    existing_usr = {}
    for op in hub(a.hub, "/api/mesh/tree"):
        for acc in op.get("accounts") or []:
            for u in acc.get("users") or []:
                existing_usr[(acc["id"], u["name"])] = u["id"]

    results = []
    for unit, (group_id, acc_name, sites) in GROUPS.items():
        print(f"\n=== {unit} ===")
        acc_id = existing_acc.get(acc_name)
        if acc_id:
            print(f"  account {acc_name} exists (id {acc_id})")
        else:
            acc = hub(a.hub, "/api/mesh/accounts",
                      {"operator_id": a.operator, "Name": acc_name, "jetstream": True})
            acc_id = acc.get("id") or acc.get("ID")
            print(f"  account {acc_name} created (id {acc_id})")

        # The business group owns the account. Without this row the group
        # boundary cannot be enforced: dataConnFor asks exactly this question
        # before it opens a connection.
        hub(a.hub, "/api/business-groups",
            {"id": group_id, "name": unit, "slug": acc_name,
             "ns_segment": acc_name, "accounts": [acc_id]})
        print(f"  business group {group_id} -> account {acc_id}")

        for site, port, container in sites:
            name = f"site-{site.lower()}"
            uid = existing_usr.get((acc_id, name))
            if not uid:
                u = hub(a.hub, "/api/mesh/users",
                        {"account_id": acc_id, "Name": name, "Bearer": False})
                uid = u.get("id") or u.get("ID")

            subtree = f"{ENTERPRISE}.{unit}.{site}.>"
            # -1 is unlimited. A limit of 0 is zero allowed, and a user minted
            # that way connects and is dropped.
            hub(a.hub, f"/api/mesh/users/{uid}/permissions",
                {"pub_allow": [subtree], "pub_deny": [], "sub_allow": [">"],
                 "sub_deny": [], "max_subscriptions": -1, "max_payload": -1,
                 "bearer_token": False}, method="PATCH")

            # Permissions live in the JWT, so the creds are fetched AFTER the
            # patch. A file downloaded earlier keeps the older rules.
            creds = hub(a.hub, f"/api/mesh/users/{uid}/creds", raw=True)
            target = f"/mesh/{name}.creds"
            subprocess.run(
                ["docker", "run", "--rm", "-i", "-v", f"{a.volume}:/mesh", "alpine",
                 "sh", "-c", f"cat > {target} && chmod 644 {target}"],
                input=creds.encode(), check=True)
            print(f"  {site:<12} user {uid:<3} {name:<20} may publish {subtree}")

            # The simulator gets the two-group model, its own branch, its own
            # identity. Saving the model restarts the factory, so the bridge is
            # configured after it.
            sim(port, "/api/uns", model)
            for _ in range(60):
                st = sim(port, "/api/status")
                if any(k.startswith(f"{unit}|") for k in (st.get("plants") or {})):
                    break
                time.sleep(2)
            sim(port, "/api/uns/live/reset", {"mode": "none"})
            sim(port, "/api/uns/live",
                {"path": f"{ENTERPRISE}|{unit}|{site}", "live": True,
                 "include_descendants": True})
            sim(port, "/api/server/start", {})
            time.sleep(2)
            sim(port, "/api/plant/control",
                {"group": unit, "plant": site, "action": "set_state", "value": True})
            # The connection name is what AMIX's observed-producers catalogue
            # shows. Matching it to the NATS user means the mesh, the catalogue
            # and the creds file all call this publisher the same thing.
            sim(port, "/api/bridge/config", {"creds": target, "client_name": name})
            sim(port, "/api/bridge/stop", {})
            time.sleep(1)
            sim(port, "/api/bridge/start", {})
            results.append((unit, site, port, name))

    print("\nwaiting for the bridges…")
    time.sleep(30)
    bad = 0
    for unit, site, port, name in results:
        st = sim(port, "/api/status").get("bridge_stats") or {}
        ok = bool(st.get("published"))
        bad += 0 if ok else 1
        print(f"  :{port} {'publishing' if ok else 'NOT publishing':<15} "
              f"{unit}|{site:<12} {name:<20} published={st.get('published')} errors={st.get('errors')}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
