import type { GraphResponse, LiveConfig, AssetTemplate } from "./types/graph";

// Same-origin so the app's optional Basic Auth cookie/credentials ride along.
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
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
  assetLibrary: () => req<AssetTemplate[]>("/api/asset-library"),
  uns: () => req<any>("/api/uns"),
  unsSave: (cfg: unknown) =>
    req<{ ok: boolean }>("/api/uns", { method: "POST", body: JSON.stringify(cfg) }),
  shift: () => req<any>("/api/shift"),
};
