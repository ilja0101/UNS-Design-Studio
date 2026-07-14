import type { AssetTemplate } from "../types/graph";

const uid = () => "n-" + Date.now().toString(36) + "-" + Math.random().toString(16).slice(2, 8);

/** Normalise a raw asset-library tag into a full UNS tag, filling the defaults
 * the config layer and editor expect (id/access/payloadSchema/…). Mirrors the
 * `{ ...newTag(), ...t }` overlay the UNS Designer uses so hub-spoke-inserted
 * tags are indistinguishable from Designer-inserted ones. */
function normalizeTag(t: any) {
  return {
    id: uid(),
    name: t?.name ?? "Tag",
    dataType: t?.dataType ?? "Float",
    unit: t?.unit ?? "",
    description: t?.description ?? "",
    access: t?.access ?? "R",
    payloadSchema: t?.payloadSchema ?? "",
    simulation: t?.simulation ? structuredClone(t.simulation) : null,
  };
}

/** Deep-clone a config, find the node at the enterprise-rooted "|"-path, and add
 * the asset as a new named "device" child (tags attached to that child) rather
 * than merging tags into the selected node — hub-spoke has no separate
 * "create node" step, so this is the only way to add named equipment. */
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
  if (!Array.isArray(node.children)) node.children = [];
  const existingNames = new Set(node.children.map((c: any) => c.name));
  let name = asset.label;
  for (let n = 2; existingNames.has(name); n++) name = `${asset.label} ${n}`;
  node.children.push({
    id: uid(),
    name,
    type: "device",
    description: asset.description ?? "",
    tags: (asset.tags ?? []).map(normalizeTag),
    children: [],
  });
  next.lastModified = new Date().toISOString();
  return next;
}
