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

  // ── Agent ──
  agentSettings: () => req<AgentSettings>("/api/agent/settings"),
  agentSettingsSave: (patch: Partial<AgentSettings> & { apiKey?: string }) =>
    req<AgentSettings>("/api/agent/settings", { method: "POST", body: JSON.stringify(patch) }),
  agentTools: () => req<{ tools: AgentTool[] }>("/api/agent/tools"),
  agentPolicy: () => req<TopicPolicy>("/api/agent/policy"),
  agentPolicySave: (policy: TopicPolicy) =>
    req<{ ok: boolean; policy: TopicPolicy }>("/api/agent/policy", {
      method: "POST",
      body: JSON.stringify(policy),
    }),
  agentPolicyCheck: (limit = 50) => req<PolicyReport>(`/api/agent/policy/check?limit=${limit}`),
  agentTopics: (contains = "", limit = 100) =>
    req<TopicPreview>(
      `/api/agent/topics?limit=${limit}&contains=${encodeURIComponent(contains)}`,
    ),
  agentSnapshots: () => req<{ snapshots: ModelSnapshot[] }>("/api/agent/snapshots"),
  agentRevert: (id: string) =>
    req<{ ok: boolean; revertedTo?: string; error?: string }>(
      `/api/agent/snapshots/${encodeURIComponent(id)}/revert`,
      { method: "POST", body: "{}" },
    ),
  conversations: () => req<{ conversations: ConversationMeta[] }>("/api/agent/conversations"),
  conversation: (id: string) =>
    req<Conversation>(`/api/agent/conversations/${encodeURIComponent(id)}`),
  conversationDelete: (id: string) =>
    req<{ ok: boolean }>(`/api/agent/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  /** Upload files for a chat message; multipart, so `req`'s JSON header must not apply. */
  attachmentUpload: async (files: File[]): Promise<{ attachments: Attachment[]; errors: string[] }> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    const r = await fetch(apiUrl("/api/agent/attachments"), {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    const data = (await r.json().catch(() => ({}))) as { attachments?: Attachment[]; errors?: string[]; error?: string };
    if (!r.ok && !data.attachments?.length) {
      throw new Error(data.errors?.join("; ") || data.error || `upload failed (HTTP ${r.status})`);
    }
    return { attachments: data.attachments ?? [], errors: data.errors ?? [] };
  },
  attachmentDelete: (id: string) =>
    req<{ ok: boolean }>(`/api/agent/attachments/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

/** Where an attachment's bytes are served (image previews, click-to-open). */
export function attachmentUrl(id: string): string {
  return apiUrl(`/api/agent/attachments/${encodeURIComponent(id)}/file`);
}

// ── Agent types ──
export interface AgentSettings {
  /** Which door to a model: the app's own backbone to the Model Gateway, or a direct endpoint. */
  route: "direct" | "mesh";
  meshProtocol: "" | "mqtt" | "nats";
  meshHost: string;
  meshPort: number;
  meshUsername: string;
  meshCreds: string;
  meshAppId: string;
  meshModel: string;
  meshPerson: string;
  meshPurpose: string;
  meshTimeout: number;
  meshPasswordSet: boolean;
  endpoint: string;
  model: string;
  maxTokens: number;
  temperature: number | null;
  reasoningEffort: string;
  maxSteps: number;
  allowWrites: boolean;
  systemPromptExtra: string;
  mcpEnabled: boolean;
  mcpToken: string;
  mcpAllowWrites: boolean;
  apiKeySet: boolean;
  configured: boolean;
  envManaged: Record<string, boolean>;
}

export interface AgentTool {
  name: string;
  description: string;
  writes: boolean;
  schema: unknown;
}

export interface PolicyLevel {
  type: string;
  required?: boolean;
  caseRule?: string;
  pattern?: string;
  allowed?: string[];
}

export interface TopicPolicy {
  name: string;
  description: string;
  separator: string;
  prefix: string;
  caseRule: string;
  maxTopicLength: number;
  levels: PolicyLevel[];
  tag: { caseRule?: string; pattern?: string; qualifiers?: string[] };
  forbiddenParts: string[];
  notes: string;
}

export interface PolicyViolation {
  code: string;
  path: string;
  message: string;
  fix: string;
}

export interface PolicyReport {
  ok: boolean;
  policy: string;
  separator: string;
  prefix: string;
  counts: { nodes: number; tags: number; topics: number; violations: number };
  reported: number;
  truncated: boolean;
  violations: PolicyViolation[];
  sampleTopics: string[];
}

export interface TopicPreview {
  total: number;
  separator: string;
  prefix: string;
  topics: Array<{ topic: string; unit: string; dataType: string; tag: string }>;
}

export interface ModelSnapshot {
  id: string;
  label: string;
  takenAt: string;
  nodes: number;
}

export interface ConversationMeta {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: number;
}

/** A file handed to the agent in chat — metadata only; the bytes stay on the server. */
export interface Attachment {
  id: string;
  name: string;
  size: number;
  mime: string;
  kind: "table" | "text" | "image" | "other";
  ts?: string;
  sheets?: Array<{ name: string; rows: number; cols: number }>;
  note?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  ts?: string;
  attachments?: Attachment[];
  tool_calls?: Array<{ id: string; function: { name: string; arguments: string } }>;
  tool_call_id?: string;
  name?: string;
  ok?: boolean;
  summary?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

/** One event off the /api/agent/chat SSE stream. */
export type AgentEvent =
  | { type: "start"; conversation: string; title?: string }
  | { type: "delta"; text: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      name: string;
      ok: boolean;
      summary: string;
      result: Record<string, unknown> | null;
    }
  | { type: "done"; stop: string; usage?: Record<string, number>; title?: string; message?: string }
  | { type: "error"; message: string; retryable?: boolean };

/** POST a turn and yield agent events as they stream in.
 *
 *  EventSource can only issue GETs, and a chat turn is a POST with a body, so
 *  the SSE frames are parsed off a fetch stream by hand. Frames are separated
 *  by a blank line; a partial frame at the end of a chunk is carried over.
 */
export async function* agentChat(
  body: { message: string; conversation?: string; attachments?: string[] },
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const r = await fetch(apiUrl("/api/agent/chat"), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    yield { type: "error", message: `chat failed (HTTP ${r.status})` };
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split = buffer.indexOf("\n\n");
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (line) {
        try {
          yield JSON.parse(line.slice(5).trim()) as AgentEvent;
        } catch {
          // A frame we can't parse is not worth killing the stream over.
        }
      }
      split = buffer.indexOf("\n\n");
    }
  }
}

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
