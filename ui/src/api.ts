import type { GraphResponse, LiveConfig, AssetTemplate } from "./types/graph";

// In AMIX governed mode the app is surfaced same-origin under a portal path
// prefix (window.__AMIX_BASE__, e.g. "/connect/design-studio/"); every backend
// call must carry it. Standalone it is undefined → paths stay at the root.
const AMIX_BASE = (window as { __AMIX_BASE__?: string }).__AMIX_BASE__ ?? "/";
export function apiUrl(path: string): string {
  return AMIX_BASE.replace(/\/$/, "") + path; // path is absolute ("/api/...")
}

// Same-origin so the app's optional Basic Auth cookie/credentials ride along.
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(apiUrl(path), {
    credentials: "same-origin",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  graph: () => req<GraphResponse>("/api/graph"),
  liveGet: () => req<LiveConfig>("/api/uns/live"),
  liveSet: (path: string, live: boolean, includeDescendants = true) =>
    req<{ ok: boolean; live: LiveConfig }>("/api/uns/live", {
      method: "POST",
      body: JSON.stringify({ path, live, include_descendants: includeDescendants }),
    }),
  liveReset: (mode: "all" | "none") =>
    req<{ ok: boolean; live: LiveConfig }>("/api/uns/live/reset", {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  simStart: () => req<{ ok: boolean; msg: string }>("/api/plants/start-all", { method: "POST", body: "{}" }),
  simStop: () => req<{ ok: boolean; msg: string }>("/api/plants/stop-all", { method: "POST", body: "{}" }),
  serverStart: () => req<{ ok: boolean; msg: string }>("/api/server/start", { method: "POST", body: "{}" }),
  serverStop: () => req<{ ok: boolean; msg: string }>("/api/server/stop", { method: "POST", body: "{}" }),
  bridgeStart: () => req<{ ok: boolean; msg: string }>("/api/bridge/start", { method: "POST", body: "{}" }),
  bridgeStop: () => req<{ ok: boolean; msg: string }>("/api/bridge/stop", { method: "POST", body: "{}" }),
  assetLibrary: () =>
    req<{ assets: AssetTemplate[] }>("/api/asset-library").then((r) => r.assets),
  uns: () => req<any>("/api/uns"),
  unsSave: (cfg: unknown) =>
    req<{ ok: boolean }>("/api/uns", { method: "POST", body: JSON.stringify(cfg) }),

  unsConfig: () => req<UnsConfig>("/api/uns"),
  unsConfigSave: (cfg: UnsConfig) =>
    req<{ ok: boolean; restarted?: string[] }>("/api/uns", {
      method: "POST",
      body: JSON.stringify(cfg),
    }),
  simulationProfiles: () => req<ProfileGroup[]>("/api/simulation-profiles"),
  assetLibraryFull: () => req<{ assets: AssetDef[] }>("/api/asset-library"),
  recipes: (group: string, plant: string) =>
    req<{ active?: string }>(`/api/recipes/${encodeURIComponent(group)}/${encodeURIComponent(plant)}`),

  payloadSchemas: () => req<{ schemas: PayloadSchema[] }>("/api/payload-schemas"),
  payloadSchemasSave: (schemas: PayloadSchema[]) =>
    req<{ ok: boolean }>("/api/payload-schemas", {
      method: "POST",
      body: JSON.stringify({ schemas }),
    }),

  vizEntities: () => req<{ kinds: string[]; entities: VizEntity[] }>("/api/viz/entities"),
  vizConfig: () => req<VizConfig>("/api/viz/config"),
  vizConfigSave: (cfg: VizConfig) =>
    req<{ ok: boolean }>("/api/viz/config", { method: "POST", body: JSON.stringify(cfg) }),
  vizValues: () => req<{ values: Record<string, unknown>; opc_ready: boolean; ts: number }>("/api/viz/values"),

  shift: () => req<ShiftStatus>("/api/shift"),
  shiftSave: (cfg: ShiftConfig) =>
    req<{ ok: boolean; status: ShiftStatus }>("/api/shift", {
      method: "POST",
      body: JSON.stringify(cfg),
    }),

  serverConfig: () => req<ServerConfig>("/api/server-config"),
  serverConfigSave: (cfg: Partial<ServerConfig>) =>
    req<ServerConfig>("/api/server-config", { method: "POST", body: JSON.stringify(cfg) }),

  plcInstances: () => req<PlcInstance[]>("/api/plc/instances"),
  plcImport: (body: {
    name: string;
    port?: number;
    autostart?: boolean;
    files: Array<{ filename: string; content: string }>;
  }) =>
    req<{ ok: boolean; msg?: string; instance?: PlcInstance; summary?: PlcImportSummary }>(
      "/api/plc/import",
      { method: "POST", body: JSON.stringify(body) },
    ),
  plcStart: (id: string) =>
    req<{ ok: boolean; msg: string }>(`/api/plc/${encodeURIComponent(id)}/start`, { method: "POST", body: "{}" }),
  plcStop: (id: string) =>
    req<{ ok: boolean; msg: string }>(`/api/plc/${encodeURIComponent(id)}/stop`, { method: "POST", body: "{}" }),
  plcDelete: (id: string) =>
    req<{ ok: boolean }>(`/api/plc/${encodeURIComponent(id)}`, { method: "DELETE" }),
  plcPatch: (id: string, patch: { name?: string; port?: number; autostart?: boolean }) =>
    req<{ ok: boolean; msg?: string; instance?: PlcInstance }>(`/api/plc/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  // Raw OT sources: an empty PLC sim the Designer edits like a UNS tree.
  plcBlank: (body: { name: string; rootName?: string; port?: number; autostart?: boolean }) =>
    req<{ ok: boolean; msg?: string; instance?: PlcInstance }>("/api/plc/blank", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  plcConfig: (id: string) =>
    req<{ ok: boolean; instance: PlcInstance; config: UnsConfig }>(
      `/api/plc/${encodeURIComponent(id)}/config`,
    ),
  plcConfigSave: (id: string, cfg: UnsConfig) =>
    req<{ ok: boolean; msg?: string; restarted?: boolean; instance?: PlcInstance }>(
      `/api/plc/${encodeURIComponent(id)}/config`,
      { method: "PUT", body: JSON.stringify({ config: cfg }) },
    ),
  plcTruth: (id: string) =>
    req<{ ok: boolean; source: string; count: number; rows: TruthRow[] }>(
      `/api/plc/${encodeURIComponent(id)}/truth`,
    ),
  plcTruthCsvUrl: (id: string) => apiUrl(`/api/plc/${encodeURIComponent(id)}/truth?format=csv`),

  bridgeConfig: () => req<BridgeConfig>("/api/bridge/config"),
  bridgeConfigSave: (cfg: Partial<BridgeConfig> & { password?: string }) =>
    req<{ ok?: boolean } & BridgeConfig>("/api/bridge/config", {
      method: "POST",
      body: JSON.stringify(cfg),
    }),
};

// ── UNS Designer model ──
export type UnsNodeType =
  | "enterprise"
  | "businessUnit"
  | "site"
  | "area"
  | "workCenter"
  | "workUnit"
  | "device"
  | "folder";

export interface RawScale {
  engLo: number;
  engHi: number;
  rawLo: number;
  rawHi: number;
}
export interface Sim {
  profile: string;
  base?: number;
  std?: number;
  min?: number;
  max?: number;
  /** Present the value as PLC counts instead of engineering units. */
  rawScale?: RawScale;
}
/** What a rawified tag really is. Written by the raw-asset inserter, never
 *  exposed over OPC-UA — it is the answer key for scoring a mapping run. */
export interface TagTruth {
  asset: string;
  assetLabel: string;
  instance: string;
  tag: string;
  unit: string;
  description: string;
  profile: string;
  role: string;
  engLo?: number;
  engHi?: number;
  rawLo?: number;
  rawHi?: number;
  decoy?: boolean;
}
export interface TruthRow extends Record<string, unknown> {
  opcPath: string;
  tag: string;
  asset: string;
  canonicalTag: string;
}
export interface UnsTag {
  id: string;
  name: string;
  dataType: string;
  unit: string;
  description: string;
  access: string;
  payloadSchema: string;
  simulation: Sim | null;
  _truth?: TagTruth;
}
export interface Recipe {
  name: string;
  params?: Record<string, unknown>;
}
export interface UnsTreeNode {
  id: string;
  name: string;
  type: UnsNodeType;
  description?: string;
  tags?: UnsTag[];
  children?: UnsTreeNode[];
  recipes?: Recipe[];
}
export interface UnsConfig {
  version?: string;
  namespaceUri?: string;
  description?: string;
  tree: UnsTreeNode;
}
export interface ProfileGroup {
  group: string;
  profiles: Array<{ id: string; label: string }>;
}
export interface AssetDef {
  id: string;
  label: string;
  category: string;
  icon?: string;
  description?: string;
  tags: Array<Partial<UnsTag>>;
}

export interface VizEntity {
  id: string;
  name: string;
  type: string;
  parentPath: string;
  kind: string;
  suggestion: string;
  mapped: boolean;
  tags: string[];
}
export interface VizConfig {
  version?: number;
  animations?: unknown;
  entities?: Record<string, { kind?: string }>;
  gauges?: unknown[];
  links?: unknown[];
  lastModified?: string;
}

export interface SchemaField {
  key: string;
  source: string;
  staticVal: string;
}
export interface PayloadSchema {
  id: string;
  name: string;
  description: string;
  fields: SchemaField[];
}

export interface ShiftStatus {
  enabled: boolean;
  state: "off" | "open" | "closed" | "dayoff";
  schedule: string;
  start: string;
  end: string;
  days: string;
  tz: string;
  running: number;
  total: number;
  next_change: string | null;
  updated: string;
}
export interface ShiftConfig {
  enabled: boolean;
  start: string;
  end: string;
  days: string;
  tz: string;
}
export interface ServerConfig {
  opc_bind_ip: string;
  opc_port: number;
  opc_client_host: string;
  tcp_port: number;
  host_ip: string;
}
export interface PlcInstance {
  id: string;
  name: string;
  configFile: string;
  port: number;
  tcpPort: number;
  autostart: boolean;
  nodes: number;
  tags: number;
  udtInstances: number;
  createdAt: string;
  running: boolean;
  endpoint: string;
}
export interface PlcImportSummary {
  records: number;
  nodes: number;
  tags: number;
  devices: number;
  folders: number;
  udt_nodes: number;
  dropped_rows: number;
  unknown_datatypes: Record<string, number>;
}
export interface BridgeConfig {
  protocol: string;
  broker_host: string;
  broker_port: number;
  topic_prefix: string;
  interval: number;
  username: string;
}
