import { describe, expect, it } from "vitest";
import { countAt, loosenTo, parseSimilarity, position, similarityParam, snap, type SimilarityScale } from "./similarity";

const scale: SimilarityScale = { floor: 0.25, ceiling: 0.6, step: 0.01, marks: [] };

describe("similarity scale", () => {
  it("snaps to hundredths inside the range", () => {
    expect(snap(0.456, scale)).toBe(0.46);
    expect(snap(0.1, scale)).toBe(0.25);
    expect(snap(0.9, scale)).toBe(0.6);
  });

  it("places values along the track", () => {
    expect(position(0.25, scale)).toBe(0);
    expect(position(0.6, scale)).toBeCloseTo(100);
  });

  it("reads the count kept at a step", () => {
    const counts = Array.from({ length: 36 }, (_, index) => 36 - index);
    expect(countAt(counts, 0.25, scale)).toBe(36);
    expect(countAt(counts, 0.45, scale)).toBe(16);
    expect(countAt(counts, 0.6, scale)).toBe(1);
    expect(countAt(null, 0.45, scale)).toBeNull();
  });

  it("leaves the account default out of the URL", () => {
    expect(similarityParam(0.45, 0.45)).toBeNull();
    expect(similarityParam(0.4, 0.45)).toBe("0.40");
  });

  it("ignores out-of-range or junk URL values", () => {
    expect(parseSimilarity("0.38", scale)).toBe(0.38);
    expect(parseSimilarity("0.9", scale)).toBeNull();
    expect(parseSimilarity("abc", scale)).toBeNull();
    expect(parseSimilarity(null, scale)).toBeNull();
  });

  it("suggests loosening to the closest match", () => {
    expect(loosenTo(0.387, 0.45, scale)).toBe(0.38);
    expect(loosenTo(0.5, 0.45, scale)).toBeNull();
    expect(loosenTo(null, 0.45, scale)).toBeNull();
  });
});
