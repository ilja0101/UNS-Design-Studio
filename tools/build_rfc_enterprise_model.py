#!/usr/bin/env python3
"""RoyalFarmersCollective as a whole agro-food cooperative: five business groups.

A fictive enterprise laid out like a real one: frozen potato products,
dehydrated potato and vegetables, beet sugar, chicory fibres and animal feed
from the other groups' by-products. Plants sit in real towns; every company,
brand and product name is made up.

Each plant is a copy of a site in uns-rfc-two-groups.json that runs the same
process (fries, drum drying, beet sugar, inulin), renamed into its group and
town, with its own products as recipes, so the active recipe the line runs is
one of that plant's products.

Writes uns-rfc-enterprise.json next to the two-group model.
"""

from __future__ import annotations

import copy
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "uns-rfc-two-groups.json")
OUT = os.path.join(HERE, "..", "uns-rfc-enterprise.json")

# The template site per process, and the group its ids and opcPaths were written under
# (a site keeps its first group's name inside, wherever it hangs in SRC now).
TEMPLATES = {
    "fries": ("Heerenveen", "FritoMaxx"),
    "drying": ("Emmeloord", "Vlokkenheim"),
    "sugar": ("Zevenbergen", "DeBietenBende"),
    "inulin": ("Roosendaal", "Wortelkracht"),
}

# Recipe parameters per process (the ones the simulator reads), products below.
PARAMS = {
    "fries": {"infeed_rate": 30, "good_ratio": 0.93, "cutter_speed_sp": 1.2, "blancher_temp_sp": 85,
              "fryer_temp_sp": 180, "freezer_temp_sp": -35, "outbound_rate": 26, "base_power_kw": 820},
    "drying": {"infeed_rate": 35, "good_ratio": 0.96, "drum_dryer_speed_sp": 0.8, "drum_temp_sp": 158,
               "outbound_rate": 8.2, "base_power_kw": 610},
    "sugar": {"infeed_rate": 100, "good_ratio": 0.85, "diffusion_temp_sp": 70, "evaporator_temp_sp": 120,
              "crystallizer_temp_sp": 80, "outbound_rate": 15, "base_power_kw": 1250},
    "inulin": {"infeed_rate": 40, "good_ratio": 0.88, "extraction_temp_sp": 80, "outbound_rate": 6.2,
               "base_power_kw": 710},
}

# group -> (what it does, [(town, process, what the plant makes, [products])])
GROUPS = {
    "FritoMaxx": ("Frozen and chilled potato products: fries, specialties and snacks.", [
        ("Steenderen", "fries", "Group head office and fries plant", ["FritoMaxx CrispCut 7mm", "FritoMaxx SuperCrunch 10mm", "FritoMaxx Steakhouse Wedges"]),
        ("Lomm", "fries", "Fries and potato specialties", ["FritoMaxx Rosti Rounds", "FritoMaxx Hash Brown Triangles", "FritoMaxx Golden Croquettes"]),
        ("Rain", "fries", "Fries for the German market", ["FritoMaxx Pommes Klassik 9mm", "FritoMaxx Kroketten Gold"]),
        ("Poperinge", "fries", "Greenfield fries and flakes plant", ["FritoMaxx Bistro Fries 12mm", "FritoMaxx Skin-On Fries 11mm"]),
    ]),
    "DroogWonder": ("Dehydrated potato and vegetable ingredients: flakes, granules and dices.", [
        ("Venray", "drying", "Dehydrated potato ingredients", ["DroogWonder Potato Flakes Fine", "DroogWonder Potato Granules", "DroogWonder Potato Dices 10mm"]),
        ("Warffum", "drying", "Dehydrated vegetables", ["DroogWonder Onion Flakes", "DroogWonder Garden Vegetable Dices", "DroogWonder Carrot Granules"]),
    ]),
    "DeBietenBende": ("Beet sugar and specialty sugars, from the growers' own beet.", [
        ("Dinteloord", "sugar", "Beet sugar factory", ["BietKristal Granulated White", "BietKristal Fondant Fine", "BietKristal Molasses"]),
        ("Vierverlaten", "sugar", "Beet sugar factory", ["BietKristal Granulated White", "BietKristal Thick Juice Concentrate"]),
        ("Puttershoek", "sugar", "Specialty sugars", ["SiroopStroom Liquid Sugar", "SiroopStroom Invert Syrup 70", "BietKristal Caster Fine"]),
    ]),
    "Wortelkracht": ("Chicory root fibres: inulin and oligofructose.", [
        ("Roosendaal", "inulin", "Chicory inulin plant", ["FiberRoot Inulin Standard", "FiberRoot Inulin HP", "OligoSoft Oligofructose Powder"]),
        ("Zwolle", "inulin", "Chicory fibre specialties", ["FiberRoot Inulin Instant", "OligoSoft Oligofructose Syrup"]),
    ]),
    "KringLoopVoer": ("Animal feed from food industry by-products: plants, and a trade organisation buying and selling them.", [
        ("Nijmegen", "drying", "Feed from food by-products", ["PulpPerfect Pressed Beet Pulp", "PulpPerfect Dried Pulp Pellets"]),
        ("Cuijk", "drying", "Potato by-product feed", ["PeelMix Potato Steam Peel Feed", "PeelMix Potato Pulp"]),
        ("Wrexham", "drying", "Feed from food by-products (UK)", ["BrewGrain Wet Brewers Grains", "VloeiVoer Liquid Feed"]),
        ("Veurne", "drying", "Feed from food by-products (BE)", ["VloeiVoer Liquid Feed", "StarchMix Wet Wheat Feed"]),
        ("Mons", "drying", "Feed from food by-products (BE)", ["StarchMix Wet Wheat Feed", "PeelMix Potato Steam Peel Feed"]),
    ]),
}


def opc(name: str) -> str:
    """How SRC writes a group in opcPath: first letter capital, the rest lower (Fritomaxx)."""
    return name[:1].upper() + name[1:].lower()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# A trade organisation has no equipment to put in ISA-95 levels: under its business group it is laid
# out by business function (sourcing, sales, logistics), and what it publishes are business events:
# orders, their status, tons and trucks. Same UNS, same enterprise and group; not an equipment tree.
TRADE = ("KringLoopVoer", "Trade", "Trade organisation, head office Alphen aan den Rijn: buys by-products from "
         "the food industry upstream and sells feed to farms and feed mills downstream.", {
    "sourcing": ("Upstream: by-products bought from food and drink producers.",
                 ["brewery-by-products", "potato-processing-by-products", "sugar-beet-pulp", "starch-and-bioethanol", "dairy-by-products"],
                 [("purchase-order-id", "String", "", {"profile": "erp_order_id"}, "Purchase order (call-off) on the supplier contract."),
                  ("purchase-order-status", "String", "", {"profile": "order_status"}, "Status of the active purchase order."),
                  ("contracted-tons", "Int", "t", {"profile": "order_quantity"}, "Tons contracted on the active order."),
                  ("collected-tons", "Float", "t", {"profile": "inbound_tons"}, "Tons collected from this supplier stream today."),
                  ("last-truck-id", "String", "", {"profile": "truck_id"}, "Last truck that collected at a supplier."),
                  ("dry-matter", "Float", "%", {"min": 18, "max": 30, "std": 0.4}, "Dry matter of the last load, from the supplier's sample.")]),
    "sales": ("Downstream: feed sold to livestock farms, feed mills and biogas plants.",
              ["dairy-farms", "pig-farms", "feed-mills", "biogas-plants"],
              [("sales-order-id", "String", "", {"profile": "erp_order_id"}, "Sales order being delivered."),
               ("sales-order-status", "String", "", {"profile": "order_status"}, "Status of the active sales order."),
               ("order-quantity", "Int", "t", {"profile": "order_quantity"}, "Tons on the active sales order."),
               ("delivered-tons", "Float", "t", {"profile": "outbound_tons"}, "Tons delivered to this segment today."),
               ("revenue", "Float", "EUR", {"profile": "revenue_eur"}, "Revenue from this segment, current period.")]),
    "logistics": ("Collection and delivery by the own and chartered tank fleet.",
                  ["tank-fleet", "dispatch"],
                  [("last-truck-id", "String", "", {"profile": "truck_id"}, "Last truck that changed status."),
                   ("trucks-on-route", "Int", "", {"min": 20, "max": 60, "std": 2}, "Trucks on the road now."),
                   ("loads-planned-today", "Int", "", {"min": 150, "max": 260, "std": 3}, "Loads planned for today."),
                   ("load-status", "String", "", {"profile": "order_status"}, "Status of the last load.")]),
})


def camel(name: str) -> str:
    return "".join(w.capitalize() for w in name.split("-"))


def trade_site() -> dict:
    group, name, what, areas = TRADE
    root = f"{opc(group)}/{name}"
    site = {"name": name, "type": "site", "id": f"site-{slug(group)}-{slug(name)}", "description": f"{group} {name}: {what}", "tags": [], "children": []}
    for area, (adesc, centres, tags) in areas.items():
        a = {"name": area, "type": "area", "id": f"area-{slug(group)}-trade-{area}", "description": adesc, "tags": [], "children": []}
        for wc in centres:
            w = {"name": wc, "type": "workCenter", "id": f"wc-{slug(group)}-trade-{area}-{wc}", "description": f"{area.capitalize()}: {wc.replace('-', ' ')}.", "tags": []}
            for tname, dtype, unit, sim, desc in tags:
                w["tags"].append({"access": "R", "dataType": dtype, "description": desc, "id": f"tag-{slug(group)}-trade-{area}-{wc}-{tname}",
                                  "name": tname, "opcPath": f"{root}/{camel(area)}/{camel(wc)}/{camel(tname)}", "payloadSchema": "standard",
                                  "qualifier": "data", "simulation": sim, "unit": unit})
            a["children"].append(w)
        site["children"].append(a)
    return site


def plant(template: dict, old_site: str, old_group: str, group: str, town: str, process: str, what: str, products: list) -> dict:
    s = json.dumps(template, ensure_ascii=False)
    # the most specific forms first: ids and loop names use the lower-case site, opcPath the capitalised group
    for old, new in [(old_group, group), (opc(old_group), opc(group)), (old_group.lower(), slug(group)),
                     (old_site, town), (old_site.lower(), slug(town))]:
        s = s.replace(old, new)
    site = json.loads(s)
    site["name"] = town
    site["id"] = f"site-{slug(town)}"
    site["description"] = (f"{group} {town}: {what.lower()}. Makes {', '.join(products)}. ISA-95 areas: production (OT/S88), "
                           "utilities (OT), quality (LIMS), maintenance (CMMS), logistics, erp and site-kpis (IT).")
    site["recipes"] = [{"name": p, "params": dict(PARAMS[process])} for p in products]
    return site


def main() -> int:
    with open(SRC, encoding="utf-8") as f:
        model = json.load(f)
    tree = model["tree"]
    found = {s["name"]: s for u in tree["children"] for s in u.get("children") or []}
    missing = [t[0] for t in TEMPLATES.values() if t[0] not in found]
    if missing:
        print(f"template sites not in {os.path.basename(SRC)}: {missing}")
        return 1

    units = []
    for group, (desc, plants) in GROUPS.items():
        unit = {"name": group, "type": "businessUnit", "id": f"bu-{slug(group)}", "description": f"{group}: {desc}", "tags": []}
        unit["children"] = []
        for town, process, what, products in plants:
            old_site, old_group = TEMPLATES[process]
            unit["children"].append(plant(copy.deepcopy(found[old_site]), old_site, old_group,
                                          group, town, process, what, products))
        if group == TRADE[0]:
            unit["children"].append(trade_site())
        units.append(unit)
    tree["children"] = units
    tree["description"] = ("RoyalFarmersCollective: agro-food cooperative of growers. Business groups: "
                           + "; ".join(f"{g} ({d.rstrip('.')})" for g, (d, _) in GROUPS.items()) + ".")
    model["description"] = ("RoyalFarmersCollective, a fictive agro-food cooperative on five business groups: "
                            + ", ".join(f"{g} ({len(p)} plant{'s' if len(p) > 1 else ''}{' and a trade organisation' if g == TRADE[0] else ''})" for g, (_, p) in GROUPS.items())
                            + ". Plants in real towns; every company, brand and product name is made up.")

    # every id unique, or the OPC UA server refuses the model
    ids = []

    def walk(n):
        if n.get("id"):
            ids.append(n["id"])
        ids.extend(t["id"] for t in n.get("tags") or [] if t.get("id"))
        for k in n.get("children") or []:
            walk(k)

    walk(tree)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        print(f"duplicate ids: {dup[:10]}")
        return 1

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)
    print(f"wrote {os.path.relpath(OUT, HERE)}: {len(ids)} ids")
    for u in units:
        print(f"  {u['name']}: {', '.join(c['name'] for c in u['children'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
