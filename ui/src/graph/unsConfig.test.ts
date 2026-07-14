import { describe, it, expect } from "vitest";
import { mergeAssetIntoConfig } from "./unsConfig";
import type { AssetTemplate } from "../types/graph";

const asset: AssetTemplate = {
  id: "centrifugal_pump",
  label: "Centrifugal Pump",
  description: "A pump",
  tags: [
    { name: "Running", dataType: "Bool", simulation: { profile: "boolean_running" } },
    { name: "MotorCurrentA", dataType: "Float", unit: "A" },
  ],
};

function cfg() {
  return {
    tree: {
      id: "ent",
      name: "Root",
      type: "enterprise",
      children: [{ id: "s1", name: "SiteA", type: "site", children: [], tags: [] }],
    },
  };
}

describe("mergeAssetIntoConfig", () => {
  it("adds the asset as a named child node (not loose tags on the target)", () => {
    const out = mergeAssetIntoConfig(cfg(), "Root|SiteA", asset);
    const site = out.tree.children[0];
    // The asset must NOT be flattened into the site's own tags.
    expect(site.tags).toEqual([]);
    expect(site.children).toHaveLength(1);
    const node = site.children[0];
    expect(node.name).toBe("Centrifugal Pump");
    expect(node.type).toBe("device");
    expect(node.description).toBe("A pump");
    expect(node.tags.map((t: any) => t.name)).toEqual(["Running", "MotorCurrentA"]);
  });

  it("fully normalises tags with the fields the config layer expects", () => {
    const out = mergeAssetIntoConfig(cfg(), "Root|SiteA", asset);
    const tag = out.tree.children[0].children[0].tags[0];
    expect(tag).toMatchObject({
      name: "Running",
      dataType: "Bool",
      unit: "",
      description: "",
      access: "R",
      payloadSchema: "",
      simulation: { profile: "boolean_running" },
    });
    expect(typeof tag.id).toBe("string");
    expect(tag.id.length).toBeGreaterThan(0);
  });

  it("gives every inserted node and tag a unique id", () => {
    const out = mergeAssetIntoConfig(cfg(), "Root|SiteA", asset);
    const node = out.tree.children[0].children[0];
    const ids = [node.id, ...node.tags.map((t: any) => t.id)];
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("de-duplicates the child name on repeated inserts", () => {
    let out = mergeAssetIntoConfig(cfg(), "Root|SiteA", asset);
    out = mergeAssetIntoConfig(out, "Root|SiteA", asset);
    out = mergeAssetIntoConfig(out, "Root|SiteA", asset);
    expect(out.tree.children[0].children.map((c: any) => c.name)).toEqual([
      "Centrifugal Pump",
      "Centrifugal Pump 2",
      "Centrifugal Pump 3",
    ]);
  });

  it("does not mutate the input config", () => {
    const input = cfg();
    const snapshot = JSON.stringify(input);
    mergeAssetIntoConfig(input, "Root|SiteA", asset);
    expect(JSON.stringify(input)).toBe(snapshot);
  });

  it("returns the config unchanged when the path does not resolve", () => {
    const input = cfg();
    const out = mergeAssetIntoConfig(input, "Root|Nowhere", asset);
    expect(out).toBe(input);
  });
});
