import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/errors";
import { hasErrors, parseFormErrors } from "./formErrors";

describe("parseFormErrors", () => {
  it("files DRF field errors under their field", () => {
    const error = new ApiError(400, "validation_error", "Invalid input.", { name: ["Missing 'name'."] });
    expect(parseFormErrors(error)).toEqual({ fields: { name: ["Missing 'name'."] }, general: [] });
  });

  it("maps API field names onto form fields", () => {
    const error = new ApiError(400, "validation_error", "Invalid input.", { target_value: ["Too small."] });
    expect(parseFormErrors(error, { fieldMap: { target_value: "target" } }).fields).toEqual({ target: ["Too small."] });
  });

  it("treats non_field_errors as form-level", () => {
    const error = new ApiError(400, "validation_error", "Invalid input.", { non_field_errors: ["Min above max."] });
    expect(parseFormErrors(error)).toEqual({ fields: {}, general: ["Min above max."] });
  });

  it("puts a conflict on the configured field", () => {
    const error = new ApiError(409, "conflict", "You already have a tag with this name.");
    expect(parseFormErrors(error, { conflictField: "name" }).fields.name).toEqual(["You already have a tag with this name."]);
    expect(parseFormErrors(error).general).toEqual(["You already have a tag with this name."]);
  });

  it("falls back to the message for anything else", () => {
    expect(parseFormErrors(new ApiError(500, "http_500", "Server error")).general).toEqual(["Server error"]);
    expect(parseFormErrors(new Error("boom")).general).toEqual(["boom"]);
  });

  it("detects errors", () => {
    expect(hasErrors({ fields: {}, general: [] })).toBe(false);
    expect(hasErrors({ fields: { x: ["1"] }, general: [] })).toBe(true);
  });
});
