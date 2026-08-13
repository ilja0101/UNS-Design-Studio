#!/usr/bin/env python3
"""Re-parent the RoyalFarmersCollective sites under two business units.

The demo runs on two business groups, one NATS account each. A site's subjects
carry its business unit, so leaving the model at six units while the mesh has
two accounts would make the namespace and the tenancy disagree: Terneuzen would
publish under KnappertjesBV while authenticating as debietenbende. Nobody
reading a subject could tell which account it came from.

Six plants, three per group. Veghel-HQ is dropped because it is GroupServices
rather than a plant, and the ask was to distribute the plants.

Writes uns-rfc-two-groups.json next to the default import. It keeps every site's
own children, so the equipment below each plant is untouched.
"""

from __future__ import annotations

import copy
import json
import os

GROUPS = {
    "FritoMaxx": ["Heerenveen", "Hoogeveen", "Emmeloord"],
    "DeBietenBende": ["Zevenbergen", "Roosendaal", "Terneuzen"],
}

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "default-uns-rfc-main-import.json")
OUT = os.path.join(HERE, "..", "uns-rfc-two-groups.json")


def main() -> int:
    with open(SRC, encoding="utf-8") as f:
        model = json.load(f)

    tree = model["tree"]
    # site name -> its node, from wherever it currently hangs.
    sites = {}
    for unit in tree.get("children") or []:
        for site in unit.get("children") or []:
            sites[site.get("name")] = site

    missing = [s for names in GROUPS.values() for s in names if s not in sites]
    if missing:
        print(f"not in the model: {missing}")
        return 1

    units = []
    for unit_name, site_names in GROUPS.items():
        # Reuse the real unit node when the model already has one, so its own
        # description and tags survive the move.
        base = next((u for u in tree.get("children") or [] if u.get("name") == unit_name), None)
        unit = copy.deepcopy(base) if base else {
            "name": unit_name, "type": "businessUnit", "description": "", "tags": [],
        }
        unit["children"] = [copy.deepcopy(sites[s]) for s in site_names]
        units.append(unit)

    tree["children"] = units
    model["description"] = (
        "RoyalFarmersCollective on two business groups. FritoMaxx and "
        "DeBietenBende hold three plants each, one NATS account per group and "
        "one user per site."
    )

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)

    print(f"wrote {os.path.relpath(OUT, HERE)}")
    for u in units:
        print(f"  {u['name']}: {', '.join(c['name'] for c in u['children'])}")
    dropped = sorted(set(sites) - {s for v in GROUPS.values() for s in v})
    print(f"  dropped: {', '.join(dropped) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
