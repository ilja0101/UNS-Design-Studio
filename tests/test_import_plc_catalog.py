"""Tests for tools/import_plc_catalog.py — PLC/Kepware catalog importer."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from import_plc_catalog import import_payloads, parse_export  # noqa: E402


# ---------------------------------------------------------------- fixtures
def converter_catalog():
    """Converter catalog JSON: 1 channel, 2 identical motor UDT instances + extras."""
    nodes = []
    for m in ("Motor01", "Motor02"):
        for tag, dt, wr in (
            ("Speed_RPM", "Float", False),
            ("Current_A", "Float", False),
            ("Running", "Boolean", False),
            ("Fault", "Boolean", False),
            ("Speed_SP", "Float", True),
        ):
            nodes.append({
                "source_id": "kepware-1",
                "node_id": f"ns=2;s=Channel1.PLC_A.{m}.{tag}",
                "browse_path": ["Channel1", "PLC_A", m, tag],
                "display_name": tag, "data_type": dt,
                "description": f"{m} {tag}", "writable": wr,
            })
    nodes.append({
        "source_id": "kepware-1",
        "node_id": "ns=2;s=Channel1.PLC_A.TotalCount",
        "browse_path": ["Channel1", "PLC_A", "TotalCount"],
        "display_name": "TotalCount", "data_type": "UInt32",
        "description": "", "writable": False,
    })
    nodes.append({
        "source_id": "kepware-1",
        "node_id": "ns=2;s=Channel1.PLC_A.BatchName",
        "browse_path": ["Channel1", "PLC_A", "BatchName"],
        "display_name": "BatchName", "data_type": "String",
        "description": "", "writable": False,
    })
    return {"loaded": True, "count": len(nodes), "nodes": nodes}


# Real Kepware CSVs put the leaf name in "Tag Name" and the full browse path in
# "Address" (Channel.Device.Group.Tag); the importer builds structure from
# Address. Aligned here with the other fixtures' paths so all three are equivalent.
KEPWARE_CSV = """Tag Name,Address,Data Type,Respect Data Type,Client Access,Scan Rate,Scaling,Raw Low,Raw High,Scaled Low,Scaled High,Scaled Data Type,Clamp Low,Clamp High,Eng Units,Description
Speed_RPM,Channel1.PLC_A.Motor01.Speed_RPM,Float,1,RO,100,None,,,,,,,,rpm,Motor 1 speed
Current_A,Channel1.PLC_A.Motor01.Current_A,Float,1,RO,100,Linear,0,27648,0,50,Float,1,1,A,Motor 1 current
Running,Channel1.PLC_A.Motor01.Running,Boolean,1,RO,100,None,,,,,,,,,
Fault,Channel1.PLC_A.Motor01.Fault,Boolean,1,RO,100,None,,,,,,,,,
Speed_SP,Channel1.PLC_A.Motor01.Speed_SP,Float,1,R/W,100,None,,,,,,,,rpm,Speed setpoint
Speed_RPM,Channel1.PLC_A.Motor02.Speed_RPM,Float,1,RO,100,None,,,,,,,,rpm,Motor 2 speed
Current_A,Channel1.PLC_A.Motor02.Current_A,Float,1,RO,100,Linear,0,27648,0,50,Float,1,1,A,Motor 2 current
Running,Channel1.PLC_A.Motor02.Running,Boolean,1,RO,100,None,,,,,,,,,
Fault,Channel1.PLC_A.Motor02.Fault,Boolean,1,RO,100,None,,,,,,,,,
Speed_SP,Channel1.PLC_A.Motor02.Speed_SP,Float,1,R/W,100,None,,,,,,,,rpm,Speed setpoint
TotalCount,Channel1.PLC_A.TotalCount,DWord,1,RO,500,None,,,,,,,,,Total pieces
BatchName,Channel1.PLC_A.BatchName,String,1,RO,1000,None,,,,,,,,,Current batch
"""


def kepware_project_json():
    def tag(name, dt, rw=0, lo=None, hi=None):
        t = {"common.ALLTYPES_NAME": name, "servermain.TAG_ADDRESS": "DB1.DBD0",
             "servermain.TAG_DATA_TYPE": dt, "servermain.TAG_READ_WRITE_ACCESS": rw,
             "servermain.TAG_SCAN_RATE_MILLISECONDS": 100}
        if lo is not None:
            t["servermain.TAG_SCALING_SCALED_LOW"] = lo
            t["servermain.TAG_SCALING_SCALED_HIGH"] = hi
        return t

    def motor(name):
        return {"common.ALLTYPES_NAME": name,
                "tags": [tag("Speed_RPM", 8), tag("Current_A", 8, lo=0, hi=50),
                         tag("Running", 1), tag("Fault", 1), tag("Speed_SP", 8, rw=1)]}

    return {"project": {"channels": [{
        "common.ALLTYPES_NAME": "Channel1",
        "devices": [{
            "common.ALLTYPES_NAME": "PLC_A",
            "tags": [tag("TotalCount", 7), tag("BatchName", 0)],
            "tag_groups": [motor("Motor01"), motor("Motor02")],
        }],
    }]}}


# ---------------------------------------------------------------- helpers
def walk_nodes(node):
    yield node
    for c in node.get("children", []):
        yield from walk_nodes(c)


def all_tags(tree):
    for n in walk_nodes(tree):
        for t in n.get("tags", []):
            yield n, t


def find_node(tree, name):
    for n in walk_nodes(tree):
        if n["name"] == name:
            return n
    return None


# ---------------------------------------------------------------- tests
@pytest.fixture(params=["catalog_json", "kepware_csv", "kepware_json"])
def imported(request):
    if request.param == "catalog_json":
        payloads = [("catalog_kepware-1.json", json.dumps(converter_catalog()))]
        cfg, s = import_payloads(payloads, name="PLC-Test")
    elif request.param == "kepware_csv":
        payloads = [("Channel1.PLC_A.csv", KEPWARE_CSV)]
        cfg, s = import_payloads(payloads, name="PLC-Test")
    else:
        payloads = [("project.json", json.dumps(kepware_project_json()))]
        cfg, s = import_payloads(payloads, name="PLC-Test")
    return cfg, s


def test_tree_structure(imported):
    cfg, summary = imported
    tree = cfg["tree"]
    assert tree["type"] == "enterprise" and tree["name"] == "PLC-Test"
    ch = find_node(tree, "Channel1")
    assert ch and ch["type"] == "folder"
    plc = find_node(tree, "PLC_A")
    assert plc and plc["type"] == "device"
    m1 = find_node(tree, "Motor01")
    assert m1 and m1["type"] == "folder"
    assert {t["name"] for t in m1["tags"]} == {"Speed_RPM", "Current_A", "Running", "Fault", "Speed_SP"}
    assert summary["tags"] == 12


def test_unique_ids(imported):
    cfg, _ = imported
    ids = [n["id"] for n in walk_nodes(cfg["tree"])]
    ids += [t["id"] for _, t in all_tags(cfg["tree"])]
    assert all(ids), "every node and tag must have an id"
    assert len(ids) == len(set(ids)), "ids must be unique"


def test_profiles_and_access(imported):
    cfg, _ = imported
    tags = {t["name"]: t for n, t in all_tags(cfg["tree"]) if n["name"] == "Motor01"}
    assert tags["Speed_RPM"]["simulation"]["profile"] == "default"
    assert tags["Speed_RPM"]["simulation"]["base"] > 0
    assert tags["Running"]["simulation"]["profile"] == "boolean_running"
    assert tags["Fault"]["simulation"]["profile"] == "boolean_fault"
    # writable -> RW command tag that holds written values
    sp = tags["Speed_SP"]
    assert sp["access"] == "RW" and sp["qualifier"] == "command"
    assert sp["simulation"]["profile"] == "hold"
    top = {t["name"]: t for n, t in all_tags(cfg["tree"]) if n["name"] == "PLC_A"}
    assert top["TotalCount"]["simulation"]["profile"] == "accumulator_generic"
    assert top["BatchName"]["dataType"] == "String"


def test_udt_detection(imported):
    cfg, summary = imported
    m1, m2 = find_node(cfg["tree"], "Motor01"), find_node(cfg["tree"], "Motor02")
    assert m1.get("udtType") == "UDT_Motor"
    assert m2.get("udtType") == "UDT_Motor"
    assert summary["udt_nodes"] >= 2


def test_scaling_feeds_sim_range():
    cfg, _ = import_payloads([("Channel1.PLC_A.csv", KEPWARE_CSV)], name="X")
    cur = next(t for n, t in all_tags(cfg["tree"])
               if n["name"] == "Motor01" and t["name"] == "Current_A")
    assert cur["simulation"]["min"] == 0.0
    assert cur["simulation"]["max"] == 50.0


def test_formats_equivalent():
    """All three formats describing the same PLC must yield the same tag paths."""
    def paths(cfg):
        out = set()
        def walk(n, pre):
            for t in n.get("tags", []):
                out.add("/".join(pre + [t["name"]]))
            for c in n.get("children", []):
                walk(c, pre + [c["name"]])
        walk(cfg["tree"], [])
        return out

    a, _ = import_payloads([("c.json", json.dumps(converter_catalog()))], name="P")
    b, _ = import_payloads([("Channel1.PLC_A.csv", KEPWARE_CSV)], name="P")
    c, _ = import_payloads([("proj.json", json.dumps(kepware_project_json()))], name="P")
    assert paths(a) == paths(b) == paths(c)


def test_multi_file_merge():
    ch2 = KEPWARE_CSV.replace("Channel1.PLC_A", "Channel2.PLC_B")
    cfg, s = import_payloads([
        ("c.json", json.dumps(converter_catalog())),
        ("plc_b.csv", ch2),
    ], name="Merged")
    assert find_node(cfg["tree"], "Channel1") and find_node(cfg["tree"], "Channel2")
    assert s["tags"] == 24


def test_source_id_filter_and_wrapper():
    data = converter_catalog()
    with pytest.raises(ValueError):
        # filter matches no source -> no tags
        import_payloads([("c.json", json.dumps(data))], name="P", source_id="other")
    cfg, s = import_payloads([("c.json", json.dumps(data))], name="P", source_id="kepware-1")
    assert s["tags"] == 12
    with pytest.raises(ValueError):
        import_payloads([("c.json", json.dumps({"nodes": []}))], name="P")


def test_unknown_datatype_warns_not_fails():
    data = {"nodes": [{"source_id": "s", "browse_path": ["Ch", "Dev", "T1"],
                       "display_name": "T1", "data_type": "WeirdType", "writable": False}]}
    cfg, s = import_payloads([("c.json", json.dumps(data))], name="P")
    assert s["unknown_datatypes"] == {"WeirdType": 1}
    t = next(t for _, t in all_tags(cfg["tree"]))
    assert t["dataType"] == "Float"


def test_opcua_nodeid_datatypes():
    """Browsed catalogs report types as OPC-UA NodeIds (i=1 Boolean, i=10 Float…)."""
    from import_plc_catalog import _map_dt
    assert _map_dt("i=1") == "Boolean"
    assert _map_dt("i=10") == "Float"
    assert _map_dt("i=11") == "Double"
    assert _map_dt("i=5") == "UInt16"
    assert _map_dt("i=12") == "String"
    assert _map_dt("ns=0;i=6") == "Int32"
    # custom / structured type reference → inert String, not a numeric walk
    assert _map_dt("ns=2;s=SortingEngineState") == "String"
    assert _map_dt("i=296") == "String"  # Argument (structured builtin)


def test_kepware_array_types():
    from import_plc_catalog import _map_dt
    assert _map_dt("Word Array") == "UInt16"
    assert _map_dt("Byte Array") == "UInt16"


def test_native_csv_structure_from_address():
    """Real Kepware CSVs carry a flat Tag Name; structure is in the Address column."""
    csv_text = (
        "Tag Name,Address,Data Type,Client Access,Description\n"
        "10_010_LSH01_DI,PLC01_Voorbewerking.Tags.Table.10_010_LSH01_DI,Boolean,RO,\n"
        "Command,PLC01_Voorbewerking.Blocks.10_010_LSH01.ioSCADA.Command,Short,R/W,\n"
    )
    cfg, _ = import_payloads([("PLC01.csv", csv_text)], name="P")
    # channel from Address becomes the top folder, not the filename
    assert find_node(cfg["tree"], "PLC01_Voorbewerking")
    assert find_node(cfg["tree"], "Table")
    assert find_node(cfg["tree"], "ioSCADA")


def test_catalog_strips_objects_and_skips_system_nodes():
    data = {"nodes": [
        {"source_id": "s", "browse_path": ["Objects", "MyChannel", "Dev", "Temp"],
         "display_name": "Temp", "data_type": "i=10", "writable": False},
        {"source_id": "s", "browse_path": ["Objects", "Server", "ServerStatus"],
         "display_name": "ServerStatus", "data_type": "i=12", "writable": False},
        {"source_id": "s", "browse_path": ["Objects", "MyChannel", "_Statistics", "TxBytes"],
         "display_name": "TxBytes", "data_type": "i=7", "writable": False},
    ]}
    cfg, s = import_payloads([("c.json", json.dumps(data))], name="P")
    assert not find_node(cfg["tree"], "Objects")
    assert not find_node(cfg["tree"], "Server")
    assert not find_node(cfg["tree"], "_Statistics")
    assert find_node(cfg["tree"], "MyChannel")
    assert s["tags"] == 1  # only the real Temp tag survives


def test_writable_pv_still_simulates_only_setpoints_hold():
    """A writable process value keeps simulating; only setpoint-named tags hold."""
    csv_text = (
        "Tag Name,Address,Data Type,Client Access,Description\n"
        "Flow_PV,Ch.Dev.Flow_PV,Float,R/W,\n"
        "Flow_SP,Ch.Dev.Flow_SP,Float,R/W,\n"
    )
    cfg, _ = import_payloads([("k.csv", csv_text)], name="P")
    tags = {t["name"]: t for _, t in all_tags(cfg["tree"])}
    assert tags["Flow_PV"]["access"] == "RW"
    assert tags["Flow_PV"]["simulation"]["profile"] == "default"   # simulates
    assert tags["Flow_PV"]["qualifier"] == "data"
    assert tags["Flow_SP"]["simulation"]["profile"] == "hold"      # setpoint holds
    assert tags["Flow_SP"]["qualifier"] == "command"


def test_multi_source_catalog_prefixes_by_source():
    data = {"nodes": [
        {"source_id": "kepware", "browse_path": ["Objects", "ChA", "Dev", "T"],
         "display_name": "T", "data_type": "i=10", "writable": False},
        {"source_id": "insort", "browse_path": ["Objects", "ChB", "Dev", "T"],
         "display_name": "T", "data_type": "i=10", "writable": False},
    ]}
    cfg, _ = import_payloads([("c.json", json.dumps(data))], name="P")
    assert {c["name"] for c in cfg["tree"]["children"]} == {"kepware", "insort"}
    # a single source_id filter drops the source-prefix layer
    cfg2, _ = import_payloads([("c.json", json.dumps(data))], name="P", source_id="kepware")
    assert {c["name"] for c in cfg2["tree"]["children"]} == {"ChA"}


def test_engine_accepts_imported_config(tmp_path, monkeypatch):
    """The generated config must load through factory.py's tree resolver."""
    cfg, _ = import_payloads([("Channel1.PLC_A.csv", KEPWARE_CSV)], name="EngineCheck")
    from uns_tree import resolve_enterprise_root
    name, root = resolve_enterprise_root(cfg["tree"])
    assert name == "EngineCheck"
    assert root["children"], "tree must have children for the address-space walk"
