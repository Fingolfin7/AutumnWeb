import { expect, it } from "vitest";
import { parseDuration } from "./duration";
it("accepts past-time minutes and hours without silently accepting malformed input", () => {
  expect(["45", "45m", "1h 30", "1h 30m", "1.5h"].map(parseDuration)).toEqual([45, 45, 90, 90, 90]);
  expect(parseDuration("1h rubbish")).toBeNaN();
  expect(parseDuration("")).toBeNaN();
});
