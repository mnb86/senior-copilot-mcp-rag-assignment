import { describe, expect, it } from "vitest";
import { fmtMs, fmtPct, groupByWave, parseBlocks, parseInline } from "./utils";

describe("parseInline", () => {
  it("tokenises bold, code, italics and citations", () => {
    const toks = parseInline("**Pump** uses `get_alarms` _(high)_ [S2]");
    expect(toks.map((t) => t.kind)).toEqual(["bold", "text", "code", "text", "italic", "text", "cite"]);
    expect(toks[6]).toEqual({ kind: "cite", value: "S2" });
  });
  it("never interprets HTML", () => {
    const toks = parseInline("<img src=x onerror=alert(1)>");
    expect(toks).toEqual([{ kind: "text", value: "<img src=x onerror=alert(1)>" }]);
  });
});

describe("parseBlocks", () => {
  it("splits paragraphs and list items", () => {
    expect(parseBlocks("Title\n- a\n\n- b")).toEqual([
      { kind: "p", text: "Title" },
      { kind: "li", text: "a" },
      { kind: "li", text: "b" },
    ]);
  });
});

describe("formatters", () => {
  it("formats durations and percentages", () => {
    expect(fmtMs(12.4)).toBe("12 ms");
    expect(fmtMs(1530)).toBe("1.53 s");
    expect(fmtPct(0.153)).toBe("15%");
    expect(fmtPct(null)).toBe("n/a");
  });
  it("groups trace records by wave", () => {
    const g = groupByWave([{ wave: 2 }, { wave: 1 }, { wave: 2 }]);
    expect(g.map(([w, r]) => [w, r.length])).toEqual([[1, 1], [2, 2]]);
  });
});
