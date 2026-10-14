import { buildChartQuery, defaultDateRange, describeFilters, EMPTY_FILTERS, readFilters, relatedPill, todayIn, writeFilters } from "./filters";

const params = (query: string) => new URLSearchParams(query);

describe("URL <-> filters", () => {
  it("reads the old page's query string", () => {
    const f = readFilters(params("chart_type=treemap&start_date=2026-01-01&end_date=2026-02-01&search=oauth&related=on&project_name=Czech&context=3&tags=1&tags=2&exclude_projects=7"));
    expect(f).toMatchObject({
      chart_type: "treemap",
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      search: "oauth",
      related: true,
      project_name: "Czech",
      context: "3",
      tags: [1, 2],
      projects: [7],
      projectMode: "exclude",
    });
  });

  it("falls back to a pie for an unknown chart type and drops junk ids", () => {
    const f = readFilters(params("chart_type=nonsense&tags=abc&tags=4&include_projects=-1"));
    expect(f.chart_type).toBe("pie");
    expect(f.tags).toEqual([4]);
    expect(f.projects).toEqual([]);
  });

  it("an include list wins and sets the picker mode", () => {
    const f = readFilters(params("include_projects=1,2&exclude_projects=3"));
    expect(f.projects).toEqual([1, 2]);
    expect(f.projectMode).toBe("include");
  });

  it("round-trips, keeping the pie default out of the URL", () => {
    const state = { ...EMPTY_FILTERS, chart_type: "radar" as const, search: "x", related: true, tags: [1, 2], projects: [5], projectMode: "include" as const };
    const text = writeFilters(state).toString();
    expect(text).toContain("chart_type=radar");
    expect(text).toContain("include_projects=5");
    expect(readFilters(params(text))).toEqual(state);
    expect(writeFilters(EMPTY_FILTERS).toString()).toBe("");
  });

  it("only writes related alongside a search", () => {
    expect(writeFilters({ ...EMPTY_FILTERS, related: true }).has("related")).toBe(false);
  });
});

describe("default date range", () => {
  const today = new Date(2026, 9, 14);
  it("looks back N units", () => {
    expect(defaultDateRange(1, "months", today)).toEqual({ start: "2026-09-14", end: "2026-10-14" });
    expect(defaultDateRange(2, "weeks", today)).toEqual({ start: "2026-09-30", end: "2026-10-14" });
    expect(defaultDateRange(10, "days", today).start).toBe("2026-10-04");
    expect(defaultDateRange(1, "years", today).start).toBe("2025-10-14");
  });
  it("clamps month ends like relativedelta", () => {
    expect(defaultDateRange(1, "months", new Date(2026, 2, 31)).start).toBe("2026-02-28");
  });
  it("supports to-date ranges", () => {
    expect(defaultDateRange(1, "month_to_date", today).start).toBe("2026-10-01");
    expect(defaultDateRange(1, "quarter_to_date", today).start).toBe("2026-10-01");
    expect(defaultDateRange(1, "year_to_date", today).start).toBe("2026-01-01");
  });
  it("treats an unknown unit as months and a zero count as one", () => {
    expect(defaultDateRange(0, "fortnights", today).start).toBe("2026-09-14");
  });
  it("reads today in the user's timezone", () => {
    const instant = new Date("2026-10-14T23:30:00Z");
    expect(todayIn("Pacific/Auckland", instant).getDate()).toBe(15);
    expect(todayIn("America/Los_Angeles", instant).getDate()).toBe(14);
  });
});

describe("chart API query", () => {
  it("related requests carry related=true, but only with a search", () => {
    const withSearch = buildChartQuery({ ...EMPTY_FILTERS, search: "oauth", related: true }, {}, null);
    expect(withSearch).toMatchObject({ search: "oauth", related: true });
    const without = buildChartQuery({ ...EMPTY_FILTERS, related: true }, {}, null);
    expect(without.related).toBeUndefined();
  });

  it("fills empty dates from the defaults and prefers the URL", () => {
    expect(buildChartQuery(EMPTY_FILTERS, { start: "2026-09-14", end: "2026-10-14" }, null)).toMatchObject({ start_date: "2026-09-14", end_date: "2026-10-14" });
    expect(buildChartQuery({ ...EMPTY_FILTERS, start_date: "2026-01-01" }, { start: "2026-09-14" }, null).start_date).toBe("2026-01-01");
  });

  it("states the context explicitly", () => {
    expect(buildChartQuery(EMPTY_FILTERS, {}, null).context).toBe("all");
    expect(buildChartQuery(EMPTY_FILTERS, {}, 4).context).toBe("4");
    expect(buildChartQuery({ ...EMPTY_FILTERS, context: "all" }, {}, 4).context).toBe("all");
    expect(buildChartQuery({ ...EMPTY_FILTERS, context: "9" }, {}, 4).context).toBe("9");
  });

  it("asks the heatmap for server-side aggregation and splits the project lists", () => {
    expect(buildChartQuery({ ...EMPTY_FILTERS, chart_type: "heatmap" }, {}, null).aggregate).toBe(true);
    const include = buildChartQuery({ ...EMPTY_FILTERS, projects: [1], projectMode: "include" }, {}, null);
    expect(include.include_projects).toEqual([1]);
    expect(include.exclude_projects).toBeUndefined();
  });
});

describe("summary pills", () => {
  const lookup = { projects: [{ id: 1, name: "Czech" }], tags: [{ id: 2, name: "Language" }], contexts: [{ id: 3, name: "Study" }] };

  it("echoes applied filters with names", () => {
    const pills = describeFilters(
      { ...EMPTY_FILTERS, start_date: "2026-01-01", context: "3", tags: [2], projects: [1], projectMode: "include" },
      lookup,
      { available: false, state: null },
    );
    expect(pills.map((p) => `${p.label}:${p.value}`)).toEqual(["From:2026-01-01", "Context:Study", "Tags:Language", "Only:Czech"]);
  });

  it("shows the related pill only for a related search, and flips it when unavailable", () => {
    const filters = { ...EMPTY_FILTERS, search: "oauth", related: true };
    const on = describeFilters(filters, lookup, { available: true, state: "included" });
    expect(on.find((p) => p.value === "related")).toMatchObject({ label: "Including" });
    const off = describeFilters(filters, lookup, { available: true, state: "unavailable" });
    expect(off.find((p) => p.label === "Related")).toMatchObject({ value: "unavailable" });
    expect(describeFilters({ ...filters, related: false }, lookup, { available: true, state: null }).map((p) => p.label)).toEqual(["Search"]);
    expect(describeFilters(filters, lookup, { available: false, state: null }).map((p) => p.label)).toEqual(["Search"]);
    expect(relatedPill("unavailable").title).toMatch(/keyword matches/);
  });
});
