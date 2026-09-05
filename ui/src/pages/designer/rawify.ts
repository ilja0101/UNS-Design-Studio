// Turn a modelled asset bundle back into raw OT data.
//
// The asset library is the answer: "Centrifugal Pump" arrives with FlowM3H in
// m³/h and a description. A real PLC hands you none of that — it hands you
// P101_DURCHFLUSS, or DB101.DBW24 holding 23224 counts. This module walks an
// asset bundle back down that ladder so a raw OT source can be built from the
// same library, and keeps a hidden `_truth` block on every tag so a mapping
// run (by a person or an AI agent) can be scored against ground truth.

import type { AssetDef, RawScale, Sim, TagTruth, UnsNodeType, UnsTag, UnsTreeNode } from "../../api";
import { uid } from "./tree";

export type RawLevel = "modelled" | "flat" | "plc" | "address";
export type RawStyle = "kepware" | "siemens" | "rockwell" | "isa" | "modbus";

export interface RawOptions {
  level: RawLevel;
  style: RawStyle;
  /** Loop / device tag the asset instance carries, e.g. "P101" or "1201". */
  instance: string;
  /** Siemens DB number for address-level naming. */
  db: number;
  /** Starting byte offset / register / file word for address-level naming. */
  address: number;
  /** Analogs become integer PLC counts (with the scaling left for the mapper). */
  rawCounts: boolean;
  keepUnits: boolean;
  keepDescriptions: boolean;
  /** Dead "spare" tags mixed in, the way a real DB is padded. */
  spares: number;
  /** Embed the answer key. */
  truth: boolean;
}

export const RAW_LEVELS: Array<{ id: RawLevel; label: string; hint: string }> = [
  { id: "modelled", label: "Modelled", hint: "The library as-is — names, units, descriptions." },
  { id: "flat", label: "Flat", hint: "Readable names, prefixed per instance. Units kept." },
  { id: "plc", label: "PLC symbolic", hint: "Vendor-style symbol names. No units, no descriptions." },
  { id: "address", label: "Raw addresses", hint: "Addresses only, analogs as integer counts. Nothing to read." },
];

export const RAW_STYLES: Array<{ id: RawStyle; label: string; levels: RawLevel[] }> = [
  { id: "kepware", label: "Kepware / generic", levels: ["plc"] },
  { id: "siemens", label: "Siemens S7 (DB)", levels: ["plc", "address"] },
  { id: "rockwell", label: "Rockwell / AB", levels: ["plc", "address"] },
  { id: "isa", label: "ISA loop tags", levels: ["plc"] },
  { id: "modbus", label: "Modbus registers", levels: ["address"] },
];

export function stylesForLevel(level: RawLevel): RawStyle[] {
  return RAW_STYLES.filter((s) => s.levels.includes(level)).map((s) => s.id);
}

// ── role inference ────────────────────────────────────────────────────────────
// Everything downstream (vendor abbreviation, ISA letters, engineering span,
// raw datatype) hangs off the role, which is read from the simulation profile
// first — that is what actually drives the value — then unit, then name.

type Kind = "analog" | "bool" | "counter" | "string";

export interface Role {
  key: string;
  isa: string;
  abbr: string;
  de: string;
  kind: Kind;
  engLo: number;
  engHi: number;
}

const R = (
  key: string,
  isa: string,
  abbr: string,
  de: string,
  kind: Kind,
  engLo = 0,
  engHi = 100,
): Role => ({ key, isa, abbr, de, kind, engLo, engHi });

const BY_PROFILE: Record<string, Role> = {
  flow_rate: R("flow", "FT", "FLOW", "DURCHFLUSS", "analog", 0, 120),
  steam_flow: R("flow", "FT", "STEAM", "DAMPF", "analog", 0, 5000),
  compressed_air: R("flow", "FT", "AIR", "DRUCKLUFT", "analog", 0, 1000),
  pressure: R("pressure", "PT", "PRES", "DRUCK", "analog", 0, 16),
  temperature_process: R("temperature", "TT", "TEMP", "TEMPERATUR", "analog", 0, 200),
  temperature_ambient: R("temperature", "TT", "ATEMP", "AUSSENTEMP", "analog", -20, 60),
  level: R("level", "LT", "LVL", "FUELLSTAND", "analog", 0, 100),
  silo_level: R("level", "LT", "LVL", "FUELLSTAND", "analog", 0, 100),
  motor_current: R("current", "IT", "CUR", "STROM", "analog", 0, 250),
  vibration: R("vibration", "VT", "VIB", "SCHWING", "analog", 0, 25),
  valve_position: R("position", "ZT", "POS", "STELLUNG", "analog", 0, 100),
  speed_rpm: R("speed", "ST", "SPD", "DREHZAHL", "analog", 0, 3000),
  power_kw: R("power", "JT", "PWR", "LEISTUNG", "analog", 0, 500),
  oee: R("percent", "QT", "OEE", "OEE", "analog", 0, 100),
  availability: R("percent", "QT", "AVAIL", "VERFUEGBAR", "analog", 0, 100),
  performance: R("percent", "QT", "PERF", "LEISTGRAD", "analog", 0, 100),
  quality: R("percent", "QT", "QUAL", "QUALITAET", "analog", 0, 100),
  quality_metric_pct: R("percent", "QT", "QUAL", "QUALITAET", "analog", 0, 100),
  quality_metric_cont: R("analog", "AT", "MEAS", "MESSWERT", "analog", 0, 100),
  remaining_useful_life: R("hours", "KT", "RUL", "RESTLAUF", "analog", 0, 20000),
  mtbf: R("hours", "KT", "MTBF", "MTBF", "analog", 0, 5000),
  mttr: R("minutes", "KT", "MTTR", "MTTR", "analog", 0, 600),
  pm_compliance: R("percent", "QT", "PMC", "WARTGRAD", "analog", 0, 100),
  days_of_supply: R("days", "KT", "DOS", "REICHWEITE", "analog", 0, 90),
  margin_pct: R("percent", "QT", "MARGIN", "MARGE", "analog", 0, 100),
  boolean_running: R("run", "XS", "RUN", "EIN", "bool"),
  boolean_fault: R("fault", "XA", "FLT", "STOERUNG", "bool"),
  boolean_alarm: R("alarm", "XA", "ALM", "ALARM", "bool"),
  quality_hold: R("hold", "XA", "HOLD", "SPERRE", "bool"),
  ctrl_watchdog: R("watchdog", "XS", "WDOG", "WACHHUND", "bool"),
  ctrl_enable: R("enable", "XS", "ENAB", "FREIGABE", "bool"),
  accumulator_good: R("counter", "QI", "TOTGOOD", "ZAEHLGUT", "counter", 0, 1e6),
  accumulator_bad: R("counter", "QI", "TOTBAD", "ZAEHLAUS", "counter", 0, 1e6),
  accumulator_energy: R("counter", "QI", "TOTKWH", "ZAEHLKWH", "counter", 0, 1e6),
  accumulator_generic: R("counter", "QI", "TOT", "ZAEHLER", "counter", 0, 1e6),
  accumulator: R("counter", "QI", "TOT", "ZAEHLER", "counter", 0, 1e6),
  counter_faults: R("counter", "QI", "CNTFLT", "ZAEHLSTOER", "counter", 0, 65535),
  corrective_wo_count: R("counter", "QI", "CNTWO", "ZAEHLAUF", "counter", 0, 65535),
  inbound_tons: R("counter", "WI", "TOTIN", "ZAEHLEIN", "counter", 0, 1e6),
  outbound_tons: R("counter", "WI", "TOTOUT", "ZAEHLAUS", "counter", 0, 1e6),
  co2_kg: R("counter", "QI", "TOTCO2", "ZAEHLCO2", "counter", 0, 1e6),
  maintenance_cost: R("counter", "QI", "COSTMNT", "KOSTWART", "counter", 0, 1e6),
  production_cost_eur: R("counter", "QI", "COSTPRD", "KOSTPROD", "counter", 0, 1e6),
  waste_cost_eur: R("counter", "QI", "COSTWST", "KOSTABF", "counter", 0, 1e6),
  revenue_eur: R("counter", "QI", "REV", "UMSATZ", "counter", 0, 1e6),
  order_quantity: R("counter", "QI", "ORDQTY", "AUFTRMNG", "counter", 0, 65535),
  batch_id: R("id", "KI", "BATCH", "CHARGE", "string"),
  lot_id: R("id", "KI", "LOT", "LOS", "string"),
  truck_id: R("id", "KI", "TRUCK", "LKW", "string"),
  erp_order_id: R("id", "KI", "ORDER", "AUFTRAG", "string"),
  order_status: R("id", "KI", "ORDSTS", "AUFTRSTS", "string"),
  recipe: R("id", "KI", "RECIPE", "REZEPT", "string"),
};

const BY_UNIT: Array<[RegExp, Role]> = [
  [/m³\/h|m3\/h|l\/min|l\/h/i, BY_PROFILE.flow_rate],
  [/^bar$|kpa|mbar|psi/i, BY_PROFILE.pressure],
  [/°c|degc/i, BY_PROFILE.temperature_process],
  [/^a$|amp/i, BY_PROFILE.motor_current],
  [/^kw$/i, BY_PROFILE.power_kw],
  [/mm\/s/i, BY_PROFILE.vibration],
  [/rpm/i, BY_PROFILE.speed_rpm],
  [/^%$/, BY_PROFILE.quality],
  [/^h$|hour/i, BY_PROFILE.remaining_useful_life],
  [/^t$|ton|^kg$/i, BY_PROFILE.accumulator_generic],
];

const BY_NAME: Array<[RegExp, Role]> = [
  [/flow/i, BY_PROFILE.flow_rate],
  [/press/i, BY_PROFILE.pressure],
  [/temp/i, BY_PROFILE.temperature_process],
  [/level/i, BY_PROFILE.level],
  [/current/i, BY_PROFILE.motor_current],
  [/vibrat/i, BY_PROFILE.vibration],
  [/position|valve/i, BY_PROFILE.valve_position],
  [/speed|rpm/i, BY_PROFILE.speed_rpm],
  [/power/i, BY_PROFILE.power_kw],
  [/count|acc$|total|hours/i, BY_PROFILE.accumulator_generic],
  [/running|run$/i, BY_PROFILE.boolean_running],
  [/fault/i, BY_PROFILE.boolean_fault],
  [/alarm/i, BY_PROFILE.boolean_alarm],
  [/setpoint|_sp$|request/i, R("setpoint", "AC", "SP", "SOLLWERT", "analog", 0, 100)],
];

const GENERIC_ANALOG = R("analog", "AT", "VAL", "WERT", "analog", 0, 100);
const GENERIC_BOOL = R("status", "XS", "STS", "STATUS", "bool");
const GENERIC_STRING = R("id", "KI", "TXT", "TEXT", "string");

export function roleFor(tag: Partial<UnsTag>): Role {
  const profile = tag.simulation?.profile ?? "";
  const byProfile = BY_PROFILE[profile];
  if (byProfile) return byProfile;
  if (profile.startsWith("ctrl")) return R("setpoint", "AC", "SP", "SOLLWERT", "analog", 0, 100);

  const dt = (tag.dataType ?? "Float").toLowerCase();
  if (tag.unit) {
    for (const [re, role] of BY_UNIT) if (re.test(tag.unit)) return role;
  }
  for (const [re, role] of BY_NAME) if (re.test(tag.name ?? "")) return role;

  if (dt.startsWith("bool")) return GENERIC_BOOL;
  if (dt.startsWith("str")) return GENERIC_STRING;
  return GENERIC_ANALOG;
}

// ── naming ────────────────────────────────────────────────────────────────────

/** Digits of the instance tag ("P101" → "101"), for ISA loop numbers. */
const loopNumber = (instance: string) => instance.replace(/\D/g, "") || instance;

const RAW_SPANS: Record<RawStyle, number> = {
  siemens: 27648, // S7 analog card full scale
  rockwell: 4095, // 12-bit AB analog input
  modbus: 4095,
  kepware: 27648,
  isa: 27648,
};

/** Address-level naming needs a vendor with actual addresses. */
function addressStyle(style: RawStyle): RawStyle {
  return style === "kepware" || style === "isa" ? "siemens" : style;
}

interface Alloc {
  byte: number; // Siemens byte offset
  bit: number; // Siemens bit within the current bool byte
  boolByte: number;
  reg: number; // Modbus holding register / AB word
  coil: number; // Modbus discrete input / AB bool word
  str: number;
}

function symbolicName(role: Role, opts: RawOptions, i: number): string {
  const inst = opts.instance || "DEV";
  switch (opts.style) {
    case "siemens":
      return `${inst}_${role.de}`;
    case "rockwell":
      return `${inst}_${role.abbr.charAt(0)}${role.abbr.slice(1).toLowerCase()}${
        role.kind === "analog" ? "_PV" : ""
      }`;
    case "isa":
      return `${role.isa}_${loopNumber(inst)}${role.kind === "analog" ? "_PV" : ""}`;
    case "modbus":
    case "kepware":
    default:
      return `${inst}_${role.abbr}${i > 0 && role.abbr === "VAL" ? String(i) : ""}`;
  }
}

function addressName(role: Role, style: RawStyle, opts: RawOptions, a: Alloc): string {
  const s = addressStyle(style);
  if (role.kind === "bool") {
    if (s === "modbus") return String(10001 + a.coil++);
    if (s === "rockwell") {
      const w = Math.floor(a.coil / 16);
      const b = a.coil % 16;
      a.coil++;
      return `B3:${w}/${b}`;
    }
    const name = `DB${opts.db}.DBX${a.boolByte}.${a.bit}`;
    a.bit += 1;
    if (a.bit > 7) {
      a.bit = 0;
      a.boolByte += 1;
    }
    return name;
  }
  if (role.kind === "string") {
    if (s === "modbus") {
      const at = 40001 + a.reg;
      a.reg += 8;
      return String(at);
    }
    if (s === "rockwell") return `ST9:${a.str++}`;
    const at = a.byte;
    a.byte += 32;
    return `DB${opts.db}.STRING${at}`;
  }
  const wide = role.kind === "counter" || !opts.rawCounts; // DINT / REAL take 4 bytes
  if (s === "modbus") {
    const at = 40001 + a.reg;
    a.reg += wide ? 2 : 1;
    return String(at);
  }
  if (s === "rockwell") {
    return opts.rawCounts && !wide ? `N7:${a.reg++}` : `F8:${a.reg++}`;
  }
  const at = a.byte;
  a.byte += wide ? 4 : 2;
  return `DB${opts.db}.${wide ? "DBD" : "DBW"}${at}`;
}

// ── the transform ─────────────────────────────────────────────────────────────

export const DEFAULT_RAW_OPTIONS: RawOptions = {
  level: "modelled",
  style: "kepware",
  instance: "P101",
  db: 101,
  address: 0,
  rawCounts: true,
  keepUnits: false,
  keepDescriptions: false,
  spares: 0,
  truth: true,
};

/** Level decides the defaults; the modal lets them be overridden afterwards. */
export function optionsForLevel(level: RawLevel, prev: RawOptions): RawOptions {
  const style = stylesForLevel(level).includes(prev.style)
    ? prev.style
    : (stylesForLevel(level)[0] ?? prev.style);
  if (level === "modelled")
    return { ...prev, level, keepUnits: true, keepDescriptions: true, rawCounts: false, spares: 0 };
  if (level === "flat")
    return { ...prev, level, keepUnits: true, keepDescriptions: true, rawCounts: false
    };
  if (level === "plc")
    return { ...prev, level, style, keepUnits: false, keepDescriptions: false, rawCounts: false };
  return { ...prev, level, style, keepUnits: false, keepDescriptions: false, rawCounts: true };
}

/** A default instance tag per asset ("Centrifugal Pump" → "P101"). */
export function suggestInstance(assetId: string, n = 101): string {
  const letter =
    /pump/.test(assetId) ? "P"
    : /valve/.test(assetId) ? "FCV"
    : /tank|silo/.test(assetId) ? "T"
    : /conveyor|belt/.test(assetId) ? "CV"
    : /reactor|vessel/.test(assetId) ? "R"
    : /boiler|steam/.test(assetId) ? "B"
    : /freezer|tunnel/.test(assetId) ? "FZ"
    : /pack|fill/.test(assetId) ? "PK"
    : /weigh|scale/.test(assetId) ? "WB"
    : /lab|quality/.test(assetId) ? "QL"
    : "EQ";
  return `${letter}${n}`;
}

function uniqueName(base: string, taken: Set<string>): string {
  if (!taken.has(base)) {
    taken.add(base);
    return base;
  }
  let n = 2;
  while (taken.has(`${base}_${n}`)) n += 1;
  const name = `${base}_${n}`;
  taken.add(name);
  return name;
}

function rawDataType(role: Role, opts: RawOptions, original: string): string {
  if (opts.level !== "address") return original;
  if (role.kind === "bool") return "Boolean";
  if (role.kind === "string") return "String";
  if (role.kind === "counter") return "Int32";
  return opts.rawCounts ? "Int16" : "Float";
}

function rawScaleFor(role: Role, opts: RawOptions): RawScale | undefined {
  if (opts.level !== "address" || !opts.rawCounts) return undefined;
  if (role.kind !== "analog") return undefined;
  return {
    engLo: role.engLo,
    engHi: role.engHi,
    rawLo: 0,
    rawHi: RAW_SPANS[addressStyle(opts.style)] ?? 27648,
  };
}

export interface RawResult {
  tags: UnsTag[];
  /** Preview rows: what the tag was, what it becomes. */
  preview: Array<{ from: string; to: string; dataType: string; unit: string }>;
  /** Tag-group label per tag, parallel to `tags` — the folder it belongs in. */
  groups: string[];
}

/** Which folder a tag lands in when the asset is grouped. Mirrors how a PLC
 *  actually organises a device: status bits, measurements, counters, setpoints. */
const GROUP_OF: Record<Kind, string> = {
  bool: "Status",
  analog: "Analog",
  counter: "Counters",
  string: "Ident",
};
function groupFor(role: Role): string {
  if (role.key === "setpoint") return "Setpoints";
  return GROUP_OF[role.kind];
}

export function rawifyAsset(
  asset: AssetDef,
  opts: RawOptions,
  existingNames: string[] = [],
): RawResult {
  const taken = new Set(existingNames);
  const alloc: Alloc = {
    byte: opts.address,
    bit: 0,
    boolByte: opts.address + 200,
    reg: opts.address,
    coil: opts.address,
    str: 0,
  };
  const tags: UnsTag[] = [];
  const preview: RawResult["preview"] = [];
  const groups: string[] = [];

  const emit = (
    name: string,
    src: Partial<UnsTag>,
    role: Role,
    sim: Sim | null,
    dataType: string,
    decoy = false,
  ) => {
    const unit = opts.keepUnits ? (src.unit ?? "") : "";
    const description = opts.keepDescriptions ? (src.description ?? "") : "";
    const scale = rawScaleFor(role, opts);
    const tag: UnsTag = {
      id: uid(),
      name,
      dataType,
      unit,
      description,
      access: src.access ?? "R",
      payloadSchema: src.payloadSchema ?? "",
      simulation: sim ? { ...sim, ...(scale ? { rawScale: scale } : {}) } : null,
    };
    if (opts.truth && opts.level !== "modelled") {
      const truth: TagTruth = {
        asset: asset.id,
        assetLabel: asset.label,
        instance: opts.instance,
        tag: src.name ?? name,
        unit: src.unit ?? "",
        description: src.description ?? "",
        profile: sim?.profile ?? "",
        role: role.key,
        ...(scale ?? {}),
        ...(decoy ? { decoy: true } : {}),
      };
      tag._truth = truth;
    }
    tags.push(tag);
    groups.push(groupFor(role));
    preview.push({ from: src.name ?? "—", to: name, dataType, unit });
  };

  asset.tags.forEach((src, i) => {
    const role = roleFor(src);
    const sim = src.simulation ? { ...src.simulation } : null;
    let name: string;
    if (opts.level === "modelled") name = src.name ?? `Tag${i}`;
    else if (opts.level === "flat") name = `${opts.instance}_${src.name ?? `Tag${i}`}`;
    else if (opts.level === "plc") name = symbolicName(role, opts, i);
    else name = addressName(role, opts.style, opts, alloc);
    emit(uniqueName(name, taken), src, role, sim, rawDataType(role, opts, src.dataType ?? "Float"));
  });

  // Padding. A real DB is full of reserved words that read zero forever, and
  // they are exactly what a mapper has to learn to ignore.
  for (let i = 0; i < Math.max(0, opts.spares); i += 1) {
    const role = i % 2 === 0 ? GENERIC_BOOL : GENERIC_ANALOG;
    const base =
      opts.level === "address"
        ? addressName(role, opts.style, opts, alloc)
        : `${opts.instance}_SPARE${i + 1}`;
    emit(
      uniqueName(base, taken),
      { name: `spare${i + 1}`, unit: "", description: "", access: "R" },
      role,
      { profile: "hold", base: 0 },
      role.kind === "bool" ? "Boolean" : opts.level === "address" ? "Int16" : "Float",
      true,
    );
  }

  return { tags, preview, groups };
}

// ── structure ─────────────────────────────────────────────────────────────────
// Dropping eleven loose tags into whatever node happened to be selected is not
// how equipment shows up in a namespace or in a PLC. An asset can bring its own
// node, and optionally split its tags into the folders a device usually has.

export type Grouping = "flat" | "kind";

export interface StructureOptions {
  /** Wrap the asset in its own child node instead of appending to the target. */
  createNode: boolean;
  nodeName: string;
  nodeType: UnsNodeType;
  grouping: Grouping;
}

export interface InsertPlan {
  /** Tags to append to the selected node (empty when a node is created). */
  tags: UnsTag[];
  /** Every tag the plan creates, in bundle order — grouping reorders the tree,
   *  the preview must stay lined up with `preview`. */
  orderedTags: UnsTag[];
  /** The node to add as a child of the selected node, when asked for one. */
  node?: UnsTreeNode;
  preview: RawResult["preview"];
  groups: string[];
  /** How many folders the plan creates — for the modal's summary line. */
  folderCount: number;
}

export function defaultNodeName(asset: AssetDef, opts: RawOptions, level: RawLevel): string {
  return level === "modelled" ? asset.label.replace(/[^A-Za-z0-9]+/g, "") : opts.instance;
}

function groupedChildren(tags: UnsTag[], groups: string[]): UnsTreeNode[] {
  const order: string[] = [];
  const buckets = new Map<string, UnsTag[]>();
  tags.forEach((t, i) => {
    const g = groups[i] ?? "Analog";
    if (!buckets.has(g)) {
      buckets.set(g, []);
      order.push(g);
    }
    buckets.get(g)!.push(t);
  });
  return order.map((g) => ({
    id: uid(),
    name: g,
    type: "folder" as UnsNodeType,
    description: "",
    tags: buckets.get(g)!,
    children: [],
  }));
}

/** What an insert will actually do to the tree. */
export function planInsert(
  asset: AssetDef,
  raw: RawOptions,
  struct: StructureOptions,
  existingTagNames: string[] = [],
  existingChildNames: string[] = [],
): InsertPlan {
  // Tags landing in their own node can use their natural names — only a flat
  // insert has to dodge the names already in the target node.
  const result = rawifyAsset(asset, raw, struct.createNode ? [] : existingTagNames);

  if (!struct.createNode) {
    return {
      tags: result.tags,
      orderedTags: result.tags,
      preview: result.preview,
      groups: result.groups,
      folderCount: 0,
    };
  }

  const taken = new Set(existingChildNames);
  let name = (struct.nodeName || "Asset").trim();
  if (taken.has(name)) {
    let n = 2;
    while (taken.has(`${name}_${n}`)) n += 1;
    name = `${name}_${n}`;
  }

  const children = struct.grouping === "kind" ? groupedChildren(result.tags, result.groups) : [];
  const node: UnsTreeNode = {
    id: uid(),
    name,
    type: struct.nodeType,
    description: asset.description ?? "",
    tags: struct.grouping === "kind" ? [] : result.tags,
    children,
  };
  return {
    tags: [],
    orderedTags: result.tags,
    node,
    preview: result.preview,
    groups: result.groups,
    folderCount: children.length,
  };
}
