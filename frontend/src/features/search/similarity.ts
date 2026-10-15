import { bootstrap } from "@/bootstrap";

/* The Related slider's scale: how close a meaning-based match must be to
   count as related. The range moves in hundredths; the named stops are
   markers along it (core.services.semantic_search.SIMILARITY_MARKS). */

export type SimilarityMark = { label: string; value: number };

export type SimilarityScale = {
  floor: number;
  ceiling: number;
  step: number;
  marks: SimilarityMark[];
};

export const DEFAULT_MARKS: SimilarityMark[] = [
  { label: "Loose", value: 0.3 },
  { label: "Moderate", value: 0.45 },
  { label: "Strict", value: 0.55 },
];

export function similarityScale(): SimilarityScale {
  const search = bootstrap().semantic_search;
  return { floor: search.min_similarity, ceiling: search.max_similarity, step: 0.01, marks: DEFAULT_MARKS };
}

/* The account's cutoff: its Profile setting, else the server default. */
export function accountSimilarity(): number {
  const { profile, semantic_search } = bootstrap();
  return profile.related_similarity ?? semantic_search.default_similarity;
}

export const fixed2 = (value: number) => value.toFixed(2);

export const sameCutoff = (a: number, b: number) => fixed2(a) === fixed2(b);

export function snap(value: number, scale: SimilarityScale): number {
  const stepped = Math.round(value / scale.step) * scale.step;
  return Math.min(scale.ceiling, Math.max(scale.floor, Number(stepped.toFixed(2))));
}

/* Percent along the track, for the --at / --fill custom properties. */
export function position(value: number, scale: SimilarityScale): number {
  return ((value - scale.floor) / (scale.ceiling - scale.floor)) * 100;
}

/* How many related matches ``value`` keeps: one count per step, floor to
   ceiling, from the search already run, so dragging makes no request. */
export function countAt(counts: readonly number[] | null | undefined, value: number, scale: SimilarityScale) {
  if (!counts?.length) return null;
  const index = Math.round((value - scale.floor) / scale.step);
  return counts[Math.max(0, Math.min(counts.length - 1, index))] ?? null;
}

/* The ?similarity= value for a cutoff: left out at the account's default. */
export function similarityParam(value: number, fallback: number): string | null {
  return sameCutoff(value, fallback) ? null : fixed2(value);
}

/* A ?similarity= URL value, or null when absent or out of range. */
export function parseSimilarity(raw: string | null | undefined, scale: SimilarityScale): number | null {
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < scale.floor || value > scale.ceiling) return null;
  return snap(value, scale);
}

/* A cutoff that keeps the closest match when ``value`` keeps none: its
   score rounded down to the step (core.utils.similarity_slider). */
export function loosenTo(best: number | null | undefined, value: number, scale: SimilarityScale): number | null {
  if (best == null || best >= value) return null;
  return Math.max(scale.floor, Math.floor(best * 100 + 1e-9) / 100);
}
