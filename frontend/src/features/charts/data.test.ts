import { buildSeries, consolidateTopN, dayKey, getChartUnit, parseDay, withAlpha } from "./data";
import { flattenHierarchy } from "./hierarchy";
import { fontSizer } from "./wordcloud";
import { buildChart, isEmptyPayload, parseKind } from "./build";

describe("top N + Other", () => {
  const rows = [
    { name: "a", total_time: 10 },
    { name: "b", total_time: 50 },
    { name: "c", total_time: 30 },
    { name: "d", total_time: 5 },
    { name: "e", total_time: 1 },
  ];
  it("keeps the biggest N and folds the rest", () => {
    const out = consolidateTopN(rows, 2);
    expect(out.map((r) => r.name)).toEqual(["b", "c", "Other (3)"]);
    expect(out[2]).toMatchObject({ total_time: 16, _isOther: true });
  });
  it("leaves short lists untouched", () => {
    expect(consolidateTopN(rows, 5)).toBe(rows);
  });
});

describe("daily series", () => {
  const rows = [
    { date: "2026-10-01", series: "a", hours: 1 },
    { date: "2026-10-01", series: "b", hours: "2" },
    { date: "2026-10-02", series: "b", hours: 1 },
    { date: "2026-10-02", series: "c", hours: 0.5 },
    { date: "2026-10-03", series: "d", hours: 0.25 },
  ];
  it("folds series beyond N into one Other series, drawn last", () => {
    const set = buildSeries(rows, 2);
    expect(set.names).toEqual(["b", "a", "Other (2)"]);
    expect(set.other).toBe("Other (2)");
    expect(set.byDay["Other (2)"]).toEqual({ "2026-10-02": 0.5, "2026-10-03": 0.25 });
    expect(set.byDay["c"]).toBeUndefined();
    expect(set.days).toEqual(["2026-10-01", "2026-10-02", "2026-10-03"]);
  });
  it("keeps every subproject series, sorted by name", () => {
    const set = buildSeries(rows);
    expect(set.names).toEqual(["a", "b", "c", "d"]);
    expect(set.other).toBeNull();
  });
  it("sums repeated days", () => {
    expect(buildSeries([{ date: "2026-10-01", series: "a", hours: 1 }, { date: "2026-10-01", series: "a", hours: 2 }], 3).byDay["a"]).toEqual({ "2026-10-01": 3 });
  });
});

describe("dates", () => {
  it("parses a day as local midnight so the axis does not shift", () => {
    const day = parseDay("2026-10-14");
    expect([day.getFullYear(), day.getMonth(), day.getDate(), day.getHours()]).toEqual([2026, 9, 14, 0]);
    expect(dayKey(day)).toBe("2026-10-14");
  });
  it("picks the axis unit by span", () => {
    expect(getChartUnit(new Date(2026, 9, 14), new Date(2026, 9, 1))).toBe("day");
    expect(getChartUnit(new Date(2026, 9, 14), new Date(2026, 8, 1))).toBe("week");
    expect(getChartUnit(new Date(2026, 9, 14), new Date(2026, 0, 1))).toBe("month");
    expect(getChartUnit(new Date(2026, 9, 14), new Date(2020, 0, 1))).toBe("year");
  });
  it("adds alpha to hex and hsl colours", () => {
    expect(withAlpha("#c98245", 0.2)).toBe("rgba(201, 130, 69, 0.2)");
    expect(withAlpha("hsl(210, 70%, 55%)", 0.6)).toBe("hsla(210, 70%, 55%, 0.6)");
    expect(withAlpha("red", 0.5)).toBe("red");
  });
});

describe("treemap data", () => {
  const tree = {
    name: "All",
    children: [
      {
        name: "Study",
        children: [
          { name: "Czech", total_time: 120, children: [{ name: "Grammar", total_time: 90 }, { name: "Empty", total_time: 0 }] },
          { name: "Solo", total_time: 60, children: [] },
          { name: "Idle", total_time: 0, children: [] },
        ],
      },
    ],
  };
  it("flattens to subproject leaves, falling back to the project itself", () => {
    const { leaves, colors } = flattenHierarchy(tree);
    expect(leaves).toEqual([
      { name: "Grammar", project: "Czech", value: 1.5 },
      { name: "Solo", project: "Solo", value: 1 },
    ]);
    expect(Object.keys(colors)).toEqual(["Czech", "Solo"]);
  });
  it("falls back to flat rows", () => {
    expect(flattenHierarchy([{ name: "a", total_time: 60 }]).leaves).toEqual([{ name: "a", project: "a", value: 1 }]);
  });
});

describe("radar and word cloud", () => {
  it("normalises font sizes into a bounded range", () => {
    const size = fontSizer([["big", 100], ["small", 1]], 1000);
    expect(size(100)).toBe(72);
    expect(size(1)).toBe(18);
    expect(fontSizer([["a", 5], ["b", 5]], 1000)(5)).toBe(72);
  });
});

describe("payload handling", () => {
  it("knows which payloads are empty", () => {
    expect(isEmptyPayload("pie", [])).toBe(true);
    expect(isEmptyPayload("pie", null)).toBe(true);
    expect(isEmptyPayload("histogram", [{ label: "0-15m", count: 0 }])).toBe(true);
    expect(isEmptyPayload("histogram", [{ label: "0-15m", count: 2 }])).toBe(false);
  });
  it("returns null when a builder has nothing to draw", () => {
    expect(buildChart("treemap", { name: "All", children: [] }, { projectLimit: 7, subprojects: false })).toBeNull();
  });
  it("swaps in the subproject variants only for a project-name filter", () => {
    const rows = [{ date: "2026-10-01", series: "a", hours: 1 }];
    const titleOf = (subprojects: boolean) => {
      const built = buildChart("stacked_area", rows, { projectLimit: 7, subprojects });
      return built?.type === "chart" ? built.config.options?.plugins?.title?.text : undefined;
    };
    expect(titleOf(false)).toBe("Daily Time by Project (Stacked)");
    expect(titleOf(true)).toBe("Daily Time by Subproject (Stacked)");
  });
  it("builds every chart kind from a minimal payload", () => {
    const opts = { projectLimit: 7, subprojects: false };
    const tally = [{ name: "a", total_time: 60 }];
    const daily = [{ date: "2026-10-01", hours: 1 }];
    const series = [{ date: "2026-10-01", series: "a", hours: 1 }];
    const cases: [Parameters<typeof buildChart>[0], unknown][] = [
      ["pie", tally],
      ["bar", tally],
      ["context", tally],
      ["line", series],
      ["stacked_area", series],
      ["cumulative", daily],
      ["heatmap", [{ weekday: 1, hour: 9, average_hours: 1 }]],
      ["histogram", [{ label: "0-15m", count: 1 }]],
      ["treemap", { name: "All", children: [{ name: "c", children: [{ name: "p", total_time: 60, children: [] }] }] }],
      ["wordcloud", [{ text: "word", weight: 3 }]],
    ];
    for (const [kind, data] of cases) expect(buildChart(kind, data, opts), kind).not.toBeNull();
  });
  it("parses chart kinds defensively", () => {
    expect(parseKind("calendar")).toBe("bar");
    expect(parseKind(null)).toBe("bar");
    expect(parseKind("sunburst")).toBe("bar");
  });
});

it("keeps chart pigments explicit and fills missing days with real zeroes", async () => {
  const { PALETTE, seriesColor } = await import("./data");
  expect(PALETTE.every(color => /^#[a-f0-9]{6}$/.test(color))).toBe(true);
  expect(PALETTE).not.toContain("#7896b8");
  expect(seriesColor("Garden")).toBe(seriesColor("Garden"));
  for (const kind of ["line", "stacked_area"] as const) {
    const built = buildChart(kind, [{ date: "2026-10-02", series: "Garden", hours: 1 }], { projectLimit: 7, subprojects: false, start: "2026-10-01", end: "2026-10-03" });
    if (built?.type !== "chart") throw new Error("Missing chart");
    expect(built.config.data.datasets[0].data).toEqual([0,1,0]);
    expect(built.config.data.datasets[0].tension).toBe(0);
    const source = JSON.stringify(built.config);
    expect(source).not.toMatch(/hsl\(|rgb\(0,\s*128,\s*0|#36a2eb|#ff6384|#4bc0c0/i);
  }
  for (const retired of ["scatter", "bubble", "radar", "status", "calendar"]) expect(parseKind(retired)).toBe("bar");
});
