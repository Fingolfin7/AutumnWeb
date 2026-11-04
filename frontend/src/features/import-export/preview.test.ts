import { describe, expect, it } from "vitest";
import { previewImport } from "./preview";

describe("local import inventory", () => {
  it("counts portable sessions within projects, including empty projects", () => {
    expect(previewImport({ format: 2, projects: [{ name: "Reading", sessions: [{}, {}] }, { name: "Walking", sessions: [] }] })).toEqual({ names: ["Reading", "Walking"], sessions: 2, portable: true });
  });
  it("keeps legacy exports readable and rejects unrelated JSON", () => {
    expect(previewImport({ Reading: { "Session History": [{}] } }).sessions).toBe(1);
    expect(() => previewImport({ message: "not an export" })).toThrow();
    expect(() => previewImport([])).toThrow();
  });
});
