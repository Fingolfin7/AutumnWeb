import { ApiError } from "@/api/errors";
import { conflictCurrent, splitErrors } from "./forms";

it("puts DRF field errors under their field and the rest above the form", () => {
  const error = new ApiError(400, "validation_error", "Invalid", { name: ["Required."], source_ids: ["Pick two."] });
  expect(splitErrors(error, ["name"])).toEqual({ fields: { name: "Required." }, general: ["source_ids: Pick two."] });
});

it("attaches a name conflict to the name field", () => {
  const error = new ApiError(409, "conflict", "Project name already exists");
  expect(splitErrors(error, ["name"], "name").fields.name).toBe("Project name already exists");
});

it("keeps other conflicts general", () => {
  const error = new ApiError(409, "conflict", "A commitment targets project 'X'. Re-point or delete that commitment first.");
  const result = splitErrors(error, ["name"], "name");
  expect(result.fields).toEqual({});
  expect(result.general).toHaveLength(1);
});

it("is empty without an error", () => {
  expect(splitErrors(null, ["name"])).toEqual({ fields: {}, general: [] });
});

it("reads the current record out of a version conflict, and nothing else", () => {
  const current = { id: 4, version: 7, name: "Alpha" };
  const conflict = new ApiError(409, "version_conflict", "The project has changed since the supplied version.", { current });
  expect(conflictCurrent<{ version?: number }>(conflict)?.version).toBe(7);
  expect(conflictCurrent(new ApiError(409, "conflict", "Project name already exists", { current }))).toBeNull();
  expect(conflictCurrent(new ApiError(400, "version_conflict", "x", { current }))).toBeNull();
  expect(conflictCurrent(new ApiError(409, "version_conflict", "x"))).toBeNull();
  expect(conflictCurrent(new Error("boom"))).toBeNull();
});

it("shows a version conflict as one general message instead of dumping its details", () => {
  const conflict = new ApiError(409, "version_conflict", "The project has changed since the supplied version.", { current: { id: 4 } });
  expect(splitErrors(conflict, ["name"], "name")).toEqual({ fields: {}, general: ["The project has changed since the supplied version."] });
});
