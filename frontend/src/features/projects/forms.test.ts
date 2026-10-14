import { ApiError } from "@/api/errors";
import { splitErrors } from "./forms";

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
