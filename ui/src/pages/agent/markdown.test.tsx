// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "./markdown";
import { sanitizeSvg } from "./SvgBlock";
import { parseChartSpec } from "./svgchart";

const html = (text: string, streaming = false) =>
  renderToStaticMarkup(<Markdown text={text} streaming={streaming} />);

describe("the agent's Markdown subset", () => {
  it("renders a GFM table with alignment and escaped pipes", () => {
    const out = html(
      ["| Rule | Count |", "|:---|---:|", "| name.case | 12 |", "| a \\| b | 1 |"].join("\n"),
    );
    expect(out).toContain("<table");
    expect(out).toContain("text-right");
    expect(out).toContain("name.case");
    expect(out).toContain("a | b");
    expect(out.match(/<tr/g)?.length).toBe(3);
  });

  it("a lone pipe line without a separator row is a paragraph, not a table", () => {
    const out = html("| just | text |");
    expect(out).not.toContain("<table");
    expect(out).toContain("<p");
  });

  it("dispatches fences by language and highlights code", () => {
    const out = html('```json\n{"a": 1}\n```');
    expect(out).toContain("hljs-attr");
    expect(out).toContain("json");
  });

  it("renders a chart fence as an SVG chart", () => {
    const spec = JSON.stringify({
      type: "bar",
      title: "Tags per area",
      series: [{ name: "tags", data: [["mixing", 40], ["filling", 25]] }],
    });
    const out = html("```chart\n" + spec + "\n```");
    expect(out).toContain("<svg");
    expect(out).toContain("Tags per area");
    expect(out).toContain("<rect");
  });

  it("an unclosed chart fence while streaming is a skeleton, not an error", () => {
    const out = html('```chart\n{"type": "bar", "ser', true);
    expect(out).toContain("chart incoming");
    expect(out).not.toContain("Could not render");
  });

  it("a bad chart spec says why", () => {
    expect(parseChartSpec("{}").error).toMatch(/series/);
    expect(parseChartSpec("nope").spec).toBeNull();
  });

  it("blockquotes, rules and headings", () => {
    const out = html("## Result\n\n> quoted\n\n---\n\ntext");
    expect(out).toContain("Result");
    expect(out).toContain("<blockquote");
    expect(out).toContain("<hr");
  });
});

describe("model-authored SVG is sanitised before it reaches the DOM", () => {
  it("strips scripts, handlers and external references, keeps the drawing", () => {
    const { svg, error } = sanitizeSvg(
      '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg" onload="x()">' +
        '<script>alert(1)</script><rect x="1" y="1" width="2" height="2" onclick="y()"/>' +
        '<use href="http://evil/x.svg#a"/><image href="http://evil/p.png"/></svg>',
    );
    expect(error).toBeNull();
    expect(svg).toContain("<rect");
    expect(svg).not.toContain("script");
    expect(svg).not.toContain("onload");
    expect(svg).not.toContain("onclick");
    expect(svg).not.toContain("evil");
    expect(svg).not.toContain("<image");
  });

  it("refuses an SVG without a viewBox, and non-SVG content", () => {
    expect(sanitizeSvg("<svg></svg>").error).toMatch(/viewBox/);
    expect(sanitizeSvg("<div/>").error).toMatch(/not an <svg>/);
  });
});
