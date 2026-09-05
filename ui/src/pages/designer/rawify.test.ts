import { describe, expect, it } from "vitest";
import type { AssetDef } from "../../api";
import {
  DEFAULT_RAW_OPTIONS,
  defaultNodeName,
  optionsForLevel,
  planInsert,
  rawifyAsset,
  roleFor,
  stylesForLevel,
  suggestInstance,
  type StructureOptions,
} from "./rawify";

const pump: AssetDef = {
  id: "centrifugal_pump",
  label: "Centrifugal Pump",
  category: "Rotating Equipment",
  tags: [
    { name: "Running", dataType: "Bool", unit: "", description: "Pump running state", simulation: { profile: "boolean_running" } },
    { name: "Fault", dataType: "Bool", unit: "", description: "Fault active", simulation: { profile: "boolean_fault" } },
    { name: "FlowM3H", dataType: "Float", unit: "m³/h", description: "Process flow", simulation: { profile: "flow_rate" } },
    { name: "MotorCurrentA", dataType: "Float", unit: "A", description: "Current", simulation: { profile: "motor_current" } },
    { name: "RunHoursAcc", dataType: "Float", unit: "h", description: "Run hours", simulation: { profile: "accumulator_generic" } },
  ],
};

const opts = (over: Partial<typeof DEFAULT_RAW_OPTIONS> = {}) => ({
  ...DEFAULT_RAW_OPTIONS,
  ...over,
});

describe("roleFor", () => {
  it("reads the simulation profile first", () => {
    expect(roleFor({ name: "Whatever", dataType: "Float", simulation: { profile: "flow_rate" } }).key).toBe("flow");
  });
  it("falls back to the unit, then the name, then the datatype", () => {
    expect(roleFor({ name: "X", dataType: "Float", unit: "bar", simulation: null }).key).toBe("pressure");
    expect(roleFor({ name: "TankLevel", dataType: "Float", unit: "", simulation: null }).key).toBe("level");
    expect(roleFor({ name: "Zzz", dataType: "Bool", unit: "", simulation: null }).key).toBe("status");
  });
});

describe("modelled level", () => {
  it("leaves the bundle untouched and writes no answer key", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "modelled", keepUnits: true, keepDescriptions: true }));
    expect(tags.map((t) => t.name)).toEqual(["Running", "Fault", "FlowM3H", "MotorCurrentA", "RunHoursAcc"]);
    expect(tags[2].unit).toBe("m³/h");
    expect(tags[2].description).toBe("Process flow");
    expect(tags.every((t) => t._truth === undefined)).toBe(true);
  });
});

describe("flat level", () => {
  it("prefixes the instance but keeps the engineering meaning", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "flat", instance: "P101", keepUnits: true, keepDescriptions: true }));
    expect(tags[2].name).toBe("P101_FlowM3H");
    expect(tags[2].unit).toBe("m³/h");
    expect(tags[2].dataType).toBe("Float");
  });
});

describe("plc level", () => {
  it("uses German symbol names for Siemens and drops the metadata", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "plc", style: "siemens", instance: "P101" }));
    expect(tags.map((t) => t.name)).toEqual([
      "P101_EIN",
      "P101_STOERUNG",
      "P101_DURCHFLUSS",
      "P101_STROM",
      "P101_ZAEHLER",
    ]);
    expect(tags.every((t) => t.unit === "" && t.description === "")).toBe(true);
  });
  it("uses ISA loop tags with the loop number", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "plc", style: "isa", instance: "P101" }));
    expect(tags[2].name).toBe("FT_101_PV");
    expect(tags[0].name).toBe("XS_101");
  });
  it("keeps the datatypes readable — no raw counts at this level", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "plc", style: "kepware" }));
    expect(tags[2].dataType).toBe("Float");
    expect(tags[2].simulation?.rawScale).toBeUndefined();
  });
});

describe("address level", () => {
  it("hands out Siemens DB addresses, packing bools into bits", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "address", style: "siemens", db: 101, address: 0 }));
    expect(tags[0].name).toBe("DB101.DBX200.0");
    expect(tags[1].name).toBe("DB101.DBX200.1");
    expect(tags[2].name).toBe("DB101.DBW0");
    expect(tags[3].name).toBe("DB101.DBW2");
    expect(tags[4].name).toBe("DB101.DBD4"); // counter → DINT, 4 bytes
  });

  it("turns analogs into integer counts and records the span in the answer key", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "address", style: "siemens" }));
    const flow = tags[2];
    expect(flow.dataType).toBe("Int16");
    expect(flow.simulation?.rawScale).toEqual({ engLo: 0, engHi: 120, rawLo: 0, rawHi: 27648 });
    expect(flow.simulation?.profile).toBe("flow_rate"); // still moves like a flow
    expect(flow._truth).toMatchObject({
      asset: "centrifugal_pump",
      tag: "FlowM3H",
      unit: "m³/h",
      role: "flow",
      rawHi: 27648,
    });
    expect(flow.unit).toBe("");
    expect(flow.description).toBe("");
  });

  it("uses Modbus registers and 12-bit spans when asked", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "address", style: "modbus", address: 0 }));
    expect(tags[0].name).toBe("10001");
    expect(tags[2].name).toBe("40001");
    expect(tags[2].simulation?.rawScale?.rawHi).toBe(4095);
  });

  it("uses AB file addressing for Rockwell", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "address", style: "rockwell", address: 0 }));
    expect(tags[0].name).toBe("B3:0/0");
    expect(tags[1].name).toBe("B3:0/1");
    expect(tags[2].name).toBe("N7:0");
  });

  it("keeps floats when raw counts are switched off", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "address", style: "siemens", rawCounts: false }));
    expect(tags[2].dataType).toBe("Float");
    expect(tags[2].name).toBe("DB101.DBD0");
    expect(tags[2].simulation?.rawScale).toBeUndefined();
  });
});

describe("spares and collisions", () => {
  it("adds dead padding tags marked as decoys", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "plc", style: "kepware", spares: 2 }));
    const spares = tags.filter((t) => t._truth?.decoy);
    expect(spares).toHaveLength(2);
    expect(spares[0].simulation?.profile).toBe("hold");
    expect(spares.map((t) => t.name)).toEqual(["P101_SPARE1", "P101_SPARE2"]);
  });

  it("never collides with tags already in the node", () => {
    const { tags } = rawifyAsset(pump, opts({ level: "plc", style: "siemens", instance: "P101" }), [
      "P101_DURCHFLUSS",
    ]);
    expect(tags[2].name).toBe("P101_DURCHFLUSS_2");
  });

  it("de-duplicates within one insert too", () => {
    const twin: AssetDef = {
      ...pump,
      tags: [pump.tags[2], { ...pump.tags[2], name: "FlowTotal" }],
    };
    const { tags } = rawifyAsset(twin, opts({ level: "plc", style: "siemens" }));
    expect(tags.map((t) => t.name)).toEqual(["P101_DURCHFLUSS", "P101_DURCHFLUSS_2"]);
  });
});

describe("option plumbing", () => {
  it("only offers styles that exist at a level", () => {
    expect(stylesForLevel("address")).toEqual(["siemens", "rockwell", "modbus"]);
    expect(stylesForLevel("plc")).toContain("isa");
  });
  it("switches to a valid style when the level changes", () => {
    const next = optionsForLevel("address", opts({ level: "plc", style: "isa" }));
    expect(stylesForLevel("address")).toContain(next.style);
    expect(next.rawCounts).toBe(true);
    expect(next.keepUnits).toBe(false);
  });
  it("suggests an instance tag per asset family", () => {
    expect(suggestInstance("centrifugal_pump")).toBe("P101");
    expect(suggestInstance("control_valve", 205)).toBe("FCV205");
  });
});


describe("insert plan", () => {
  const struct = (over: Partial<StructureOptions> = {}): StructureOptions => ({
    createNode: true,
    nodeName: "P101",
    nodeType: "device",
    grouping: "flat",
    ...over,
  });

  it("gives the asset its own node instead of loose tags", () => {
    const plan = planInsert(pump, opts({ level: "plc", style: "siemens" }), struct());
    expect(plan.tags).toEqual([]);
    expect(plan.node?.name).toBe("P101");
    expect(plan.node?.type).toBe("device");
    expect(plan.node?.tags).toHaveLength(5);
    expect(plan.node?.children).toEqual([]);
    expect(plan.folderCount).toBe(0);
  });

  it("keeps a bundle-ordered tag list for the preview", () => {
    const plan = planInsert(pump, opts({ level: "plc", style: "siemens" }), struct({ grouping: "kind" }));
    expect(plan.orderedTags.map((t) => t.name)).toEqual([
      "P101_EIN",
      "P101_STOERUNG",
      "P101_DURCHFLUSS",
      "P101_STROM",
      "P101_ZAEHLER",
    ]);
    expect(plan.orderedTags).toHaveLength(plan.preview.length);
    expect(plan.groups).toEqual(["Status", "Status", "Analog", "Analog", "Counters"]);
  });

  it("splits the tags into the folders a device actually has", () => {
    const plan = planInsert(pump, opts({ level: "plc", style: "siemens" }), struct({ grouping: "kind" }));
    expect(plan.node?.tags).toEqual([]);
    expect(plan.node?.children?.map((c) => c.name)).toEqual(["Status", "Analog", "Counters"]);
    expect(plan.node?.children?.[0].tags?.map((t) => t.name)).toEqual(["P101_EIN", "P101_STOERUNG"]);
    expect(plan.node?.children?.[2].tags).toHaveLength(1);
    expect(plan.folderCount).toBe(3);
  });

  it("keeps appending straight into the node when asked to", () => {
    const plan = planInsert(pump, opts({ level: "modelled" }), struct({ createNode: false }));
    expect(plan.node).toBeUndefined();
    expect(plan.tags.map((t) => t.name)).toContain("FlowM3H");
  });

  it("never collides with a sibling node of the same name", () => {
    const plan = planInsert(pump, opts({ level: "plc" }), struct(), [], ["P101", "P101_2"]);
    expect(plan.node?.name).toBe("P101_3");
  });

  it("does not rename tags for collisions once they live in their own node", () => {
    const plan = planInsert(pump, opts({ level: "plc", style: "siemens" }), struct(), ["P101_DURCHFLUSS"]);
    expect(plan.node?.tags?.map((t) => t.name)).toContain("P101_DURCHFLUSS");
  });

  it("names the node after the asset in the UNS and after the loop tag when raw", () => {
    expect(defaultNodeName(pump, opts(), "modelled")).toBe("CentrifugalPump");
    expect(defaultNodeName(pump, opts({ instance: "P205" }), "address")).toBe("P205");
  });
});
