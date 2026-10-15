import { buildSeries, consolidateTopN, dayKey, getChartUnit, parseDay, withAlpha } from "./data";
import { groupScatter } from "./basic";
import { flattenHierarchy } from "./hierarchy";
import { radarMetrics } from "./analysis";
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

describe("scatter grouping", () => {
  const rows = [
    { x: "2026-10-01T10:00:00Z", y: 1, series: "a" },
    { x: "2026-10-02T10:00:00Z", y: 3, series: "b" },
    { x: "2026-10-03T10:00:00Z", y: 0.5, series: "c" },
  ];
  it("ranks by total hours and folds the rest", () => {
    const groups = groupScatter(rows, 1);
    expect(groups.map((g) => g.name)).toEqual(["b", "Other (2)"]);
    expect(groups[1]!.other).toBe(true);
    expect(groups[1]!.points.every((p) => p.projectName === "Other (2)")).toBe(true);
  });
  it("sorts subproject series by name", () => {
    expect(groupScatter(rows).map((g) => g.name)).toEqual(["a", "b", "c"]);
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
  it("takes the top six with time and inverts recency", () => {
    const rows = Array.from({ length: 8 }, (_, i) => ({ name: `p${i}`, total_time: i * 60, session_count: 2, subproject_count: 1, days_since_update: i * 10 }));
    const metrics = radarMetrics(rows);
    expect(metrics).toHaveLength(6);
    expect(metrics[0]).toMatchObject({ name: "p7", totalTime: 7, avgSessionLength: 3.5, recency: 0 });
    expect(radarMetrics([{ name: "x", total_time: 60, session_count: 1, subproject_count: 0 }])[0]!.recency).toBe(15);
  });
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
    expect(buildChart("radar", [{ name: "a", total_time: 0, session_count: 0, subproject_count: 0 }], { projectLimit: 7, subprojects: false })).toBeNull();
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
      ["status", [{ status: "active", count: 1, total_time: 60 }]],
      ["scatter", [{ x: "2026-10-01T10:00:00Z", y: 1, series: "a" }]],
      ["line", series],
      ["stacked_area", series],
      ["cumulative", daily],
      ["calendar", daily],
      ["heatmap", [{ weekday: 1, hour: 9, average_hours: 1 }]],
      ["histogram", [{ label: "0-15m", count: 1 }]],
      ["radar", [{ name: "a", total_time: 60, session_count: 1, subproject_count: 0 }]],
      ["bubble", [{ name: "t", tag_id: 1, total_time: 60, project_count: 1, color: "#aabbcc" }]],
      ["treemap", { name: "All", children: [{ name: "c", children: [{ name: "p", total_time: 60, children: [] }] }] }],
      ["wordcloud", [{ text: "word", weight: 3 }]],
    ];
    for (const [kind, data] of cases) expect(buildChart(kind, data, opts), kind).not.toBeNull();
  });
  it("parses chart kinds defensively", () => {
    expect(parseKind("calendar")).toBe("calendar");
    expect(parseKind(null)).toBe("pie");
    expect(parseKind("sunburst")).toBe("pie");
  });
});
