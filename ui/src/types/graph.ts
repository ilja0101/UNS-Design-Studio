export type NodeType =
  | "enterprise"
  | "businessUnit"
  | "site"
  | "area"
  | "workCenter"
  | "workUnit"
  | "device"
  | "system";

export interface GraphNode {
  id: string; // "|"-joined enterprise-rooted name path
  type: NodeType;
  name: string;
  parentId: string | null;
  depth: number;
  live: boolean;
  running: boolean;
  hasTags: boolean;
  tagCount: number;
  plantKey: string | null;
  publishRate: number;
  description?: string;
}

export interface GraphResponse {
  enterprise: { id: string; name: string };
  singleBusinessUnit: boolean;
  nodes: GraphNode[];
  liveMode: "all" | "explicit";
  simulatorRunning: boolean;
  server: { running: boolean };
  bridge: {
    connected: boolean;
    running: boolean;
    protocol: string;
    msgsPerSec: number;
    perPlant: Record<string, number>;
  };
}

export interface LiveConfig {
  mode: "all" | "explicit";
  paths: string[];
}

/** Asset-library template (from /api/asset-library). */
export interface AssetTemplate {
  id: string;
  label: string;
  icon?: string;
  category?: string;
  description?: string;
  tags: Array<Record<string, unknown>>;
}
