/* The maths behind the "time split" editor: dividing a session's time across
   its subprojects in whole percents, with rows that can be locked. Ported from
   core/static/core/js/allocation_editor.js and kept free of React so the rules
   can be tested.

   Vocabulary: a *row* is one selected subproject with a percent `value` (whole
   number, 1..100) and a `locked` flag. The API stores the same thing as basis
   points (`allocation_bp`, 10000 = 100%, each >= 1, total <= 10000), so
   `value * 100`. A total below 100% is allowed: the remainder is time that
   belongs to the project but to no subproject. */

export interface AllocationItem {
  id: number;
  name: string;
  /** Stored allocation in basis points; 0 or missing when there is none yet. */
  bp?: number;
}

export interface AllocationRow {
  id: number;
  name: string;
  /** Whole percent. */
  value: number;
  locked: boolean;
}

/** The shape the API takes (SubprojectAllocationWrite). */
export interface AllocationWrite {
  subproject_id: number;
  allocation_bp: number;
}

/** Segment colours, by row position (the old editor's palette). */
export const ALLOCATION_COLORS = ["#7896b8", "#7ca36a", "#b9a66a", "#9b83a7", "#4e9a8e", "#c98245"];

export function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/* Largest-remainder split of `total` (rounded to a whole number) in
   proportion to `weights`. Equal split when every weight is zero. The result
   always sums to `total`; ties go to the earlier row. */
export function distribute(total: number, weights: number[]): number[] {
  const count = weights.length;
  if (!count) return [];
  const whole = Math.max(0, Math.round(total));
  const clean = weights.map((weight) => Math.max(0, weight));
  const weightTotal = clean.reduce((sum, weight) => sum + weight, 0);
  const raw = weightTotal ? clean.map((weight) => (whole * weight) / weightTotal) : clean.map(() => whole / count);
  const result = raw.map(Math.floor);
  const left = whole - result.reduce((sum, value) => sum + value, 0);
  const order = raw
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
  for (let i = 0; i < left; i += 1) result[order[i]!.index]! += 1;
  return result;
}

/** 100% split as evenly as whole percents allow: 3 rows -> 34 / 33 / 33. */
export function evenValues(count: number): number[] {
  return distribute(100, Array<number>(count).fill(1));
}

/* Like distribute(), but every share is at least 1: reserve 1 for each row,
   split the rest by how much each row has above 1. */
export function distributePositive(total: number, weights: number[]): number[] {
  if (!weights.length) return [];
  const remainder = distribute(
    total - weights.length,
    weights.map((weight) => Math.max(0, weight - 1)),
  );
  return remainder.map((value) => value + 1);
}

/* Percents for rows that already have stored allocations. Basis points are
   rounded to whole percents with the largest-remainder rule (ties to the
   lower subproject id), never exceeding the stored total. With nothing stored
   the split is even.

   Beyond the old editor: if the stored values add up to more than 100%
   (sessions created before allocations existed carry 10000bp per subproject),
   they are scaled back to 100% in proportion instead of showing "Total 200%",
   which the API would refuse to save. */
export function initialValues(items: AllocationItem[]): number[] {
  const bps = items.map((item) => Number(item.bp || 0));
  const storedTotal = bps.reduce((sum, value) => sum + value, 0);
  if (!Math.round(storedTotal / 100)) return evenValues(items.length);
  if (storedTotal > 10000) return distributePositive(100, bps);
  const totalPercent = Math.min(100, Math.round(storedTotal / 100));
  const floors = bps.map((value) => Math.floor(value / 100));
  const left = totalPercent - floors.reduce((sum, value) => sum + value, 0);
  const order = bps
    .map((value, index) => ({ index, fraction: value % 100 }))
    .sort((a, b) => b.fraction - a.fraction || items[a.index]!.id - items[b.index]!.id);
  for (let i = 0; i < left; i += 1) floors[order[i]!.index]! += 1;
  return floors;
}

/** Rows for the selected subprojects, in id order. `even` ignores stored bp. */
export function makeRows(items: AllocationItem[], even = false): AllocationRow[] {
  const sorted = [...items].sort((a, b) => a.id - b.id);
  const values = even ? evenValues(sorted.length) : initialValues(sorted);
  return sorted.map((item, index) => ({ id: item.id, name: item.name, value: values[index]!, locked: false }));
}

export function rowsTotal(rows: AllocationRow[]): number {
  return rows.reduce((sum, row) => sum + row.value, 0);
}

export function lockedTotal(rows: AllocationRow[]): number {
  return rows.reduce((sum, row) => sum + (row.locked ? row.value : 0), 0);
}

/** Percent of the session that belongs to no subproject. */
export function unallocated(rows: AllocationRow[]): number {
  return Math.max(0, 100 - rowsTotal(rows));
}

/** True when nothing is locked and the values are the even split. */
export function isEvenSplit(rows: AllocationRow[]): boolean {
  const even = evenValues(rows.length);
  return !rows.some((row) => row.locked) && rows.every((row, index) => row.value === even[index]);
}

/* Set one row's percent. Locked rows never change; the unlocked rest share
   what is left (100 minus the locked total) in proportion to their current
   values, each keeping at least 1. A row can't take more than leaves 1% for
   every other unlocked row. With no other unlocked row the total can fall
   below 100% (the remainder is unallocated). */
export function setRowValue(rows: AllocationRow[], index: number, rawValue: number): AllocationRow[] {
  const row = rows[index];
  if (!row || row.locked) return rows;
  const available = 100 - lockedTotal(rows);
  const others = rows.map((candidate, candidateIndex) => ({ candidate, candidateIndex })).filter((item) => item.candidateIndex !== index && !item.candidate.locked);
  const maximum = Math.max(1, available - others.length);
  const value = clamp(Math.round(rawValue || 1), 1, maximum);
  const next = rows.map((candidate) => ({ ...candidate }));
  next[index]!.value = value;
  if (others.length) {
    const values = distributePositive(
      available - value,
      others.map((item) => item.candidate.value),
    );
    others.forEach((item, position) => {
      next[item.candidateIndex]!.value = values[position]!;
    });
  }
  return next;
}

export function toggleLock(rows: AllocationRow[], index: number): AllocationRow[] {
  return rows.map((row, position) => (position === index ? { ...row, locked: !row.locked } : row));
}

/** "Distribute evenly": even split, every lock released. */
export function evenRows(rows: AllocationRow[]): AllocationRow[] {
  const values = evenValues(rows.length);
  return rows.map((row, index) => ({ ...row, value: values[index]!, locked: false }));
}

/** API form: percents to basis points, in subproject id order. */
export function toAllocationWrites(rows: AllocationRow[]): AllocationWrite[] {
  return [...rows].sort((a, b) => a.id - b.id).map((row) => ({ subproject_id: row.id, allocation_bp: row.value * 100 }));
}

/** Whether two allocation lists describe the same split (order-insensitive). */
export function sameAllocations(a: AllocationWrite[], b: AllocationWrite[]): boolean {
  if (a.length !== b.length) return false;
  const byId = new Map(b.map((item) => [item.subproject_id, item.allocation_bp]));
  return a.every((item) => byId.get(item.subproject_id) === item.allocation_bp);
}

/** One-line summary for the collapsed header: "Custom · 60 / 30 · 10% unallocated". */
export function summarize(rows: AllocationRow[]): string {
  const remainder = unallocated(rows);
  return `${isEvenSplit(rows) ? "Even split" : "Custom"} · ${rows.map((row) => row.value).join(" / ")}${remainder ? ` · ${remainder}% unallocated` : ""}`;
}
