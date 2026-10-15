import {
  buildExportQuery,
  EMPTY_EXPORT_FORM,
  exportFilename,
  formatExport,
  orderContexts,
  projectsInScope,
  validateExport,
} from "./exportQuery";

const form = (patch: Partial<typeof EMPTY_EXPORT_FORM>) => ({ ...EMPTY_EXPORT_FORM, ...patch });

describe("buildExportQuery", () => {
  it("sends nothing for an untouched form", () => {
    expect(buildExportQuery(EMPTY_EXPORT_FORM).toString()).toBe("");
  });

  it("maps filters to API parameters", () => {
    const query = buildExportQuery(
      form({
        startDate: "2026-01-01",
        endDate: "2026-02-01",
        context: "3",
        tags: [1, 2],
        projectName: " Zz ",
        projects: [5, 6],
        projectMode: "include",
      }),
    );
    expect(query.get("start_date")).toBe("2026-01-01");
    expect(query.get("end_date")).toBe("2026-02-01");
    expect(query.get("context_ids")).toBe("3");
    expect(query.get("tag_ids")).toBe("1,2");
    expect(query.get("project_name")).toBe("Zz");
    expect(query.get("project_ids")).toBe("5,6");
    expect(query.has("exclude_project_ids")).toBe(false);
  });

  it("uses exclude_project_ids in exclude mode", () => {
    const query = buildExportQuery(form({ projects: [9], projectMode: "exclude" }));
    expect(query.get("exclude_project_ids")).toBe("9");
    expect(query.has("project_ids")).toBe(false);
  });

  it("sends format options only when they apply", () => {
    expect(buildExportQuery(form({ autumnCompatible: true })).has("autumn_compatible")).toBe(false);
    const legacy = buildExportQuery(form({ legacy: true, autumnCompatible: true, compress: true }));
    expect(legacy.get("export_format")).toBe("1");
    expect(legacy.get("autumn_compatible")).toBe("true");
    expect(legacy.get("compress")).toBe("true");
  });
});

describe("exportFilename", () => {
  it("falls back like the old view", () => {
    expect(exportFilename({ outputFile: "", projectName: "" })).toBe("projects.json");
    expect(exportFilename({ outputFile: "", projectName: "Zz Test" })).toBe("Zz Test.json");
    expect(exportFilename({ outputFile: "backup", projectName: "x" })).toBe("backup.json");
    expect(exportFilename({ outputFile: "keep.json", projectName: "" })).toBe("keep.json");
  });

  it("removes characters a file system rejects", () => {
    expect(exportFilename({ outputFile: "a/b:c", projectName: "" })).toBe("a_b_c.json");
  });
});

describe("validateExport", () => {
  it("rejects an end before the start", () => {
    expect(validateExport({ startDate: "2026-02-01", endDate: "2026-01-01" }).end_date).toBeTruthy();
    expect(validateExport({ startDate: "2026-01-01", endDate: "2026-01-01" })).toEqual({});
    expect(validateExport({ startDate: "", endDate: "2026-01-01" })).toEqual({});
  });
});

describe("projectsInScope", () => {
  const projects = [
    { id: 1, context: { id: 10 }, tags: [{ id: 100 }] },
    { id: 2, context: { id: 20 }, tags: [{ id: 100 }, { id: 200 }] },
    { id: 3, context: null, tags: [] },
  ];

  it("returns everything with no scope", () => {
    expect(projectsInScope(projects, "", [], []).map((p) => p.id)).toEqual([1, 2, 3]);
  });

  it("narrows by context and by any chosen tag", () => {
    expect(projectsInScope(projects, "20", [], []).map((p) => p.id)).toEqual([2]);
    expect(projectsInScope(projects, "", [200], []).map((p) => p.id)).toEqual([2]);
    expect(projectsInScope(projects, "", [100], []).map((p) => p.id)).toEqual([1, 2]);
  });

  it("keeps ticked projects visible", () => {
    expect(projectsInScope(projects, "20", [], [3]).map((p) => p.id)).toEqual([2, 3]);
  });
});

describe("orderContexts", () => {
  it("pins General first", () => {
    expect(orderContexts([{ name: "Craft" }, { name: "General" }, { name: "Study" }]).map((c) => c.name)).toEqual([
      "General",
      "Craft",
      "Study",
    ]);
  });
});

describe("formatExport", () => {
  it("indents plain exports and leaves compressed ones alone", () => {
    expect(formatExport('{"a":1}', false)).toBe('{\n    "a": 1\n}');
    expect(formatExport('{"a":1}', true)).toBe('{"a":1}');
    expect(formatExport("not json", false)).toBe("not json");
  });
});
