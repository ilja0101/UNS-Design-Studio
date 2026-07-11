import type { AssetTemplate } from "../types/graph";

/** Deep-clone a config, find the node at the enterprise-rooted "|"-path, append
 * the asset's tags to it, and return the new config. Mirrors the legacy
 * uns_editor merge (append tag bundle to the selected node). */
export function mergeAssetIntoConfig(cfg: any, nodePath: string, asset: AssetTemplate): any {
  const next = structuredClone(cfg);
  const parts = nodePath.split("|");
  let node = next?.tree;
  if (!node || node.name !== parts[0]) return cfg;
  for (const name of parts.slice(1)) {
    const child = (node.children ?? []).find((c: any) => c.name === name);
    if (!child) return cfg;
    node = child;
  }
  if (!Array.isArray(node.tags)) node.tags = [];
  const existing = new Set(node.tags.map((t: any) => t.name));
  for (const tag of asset.tags ?? []) {
    const t = tag as any;
    if (!existing.has(t.name)) node.tags.push(structuredClone(t));
  }
  next.lastModified = new Date().toISOString();
  return next;
}
