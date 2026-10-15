import type { Commitment } from "@/api/types";

/* Number and date display shared by the commitment pages. */

/** Python-style float text: whole values keep one decimal ("-180.0"), like the template's raw floats. */
export function floatText(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? rounded.toFixed(1) : String(rounded);
}

export const signed = (value: number, text: string = String(value)) => (value >= 0 ? `+${text}` : text);

export const unitSuffix = (type: string) => (type === "time" ? "m" : "");

/** "Oct 12" */
export function monthDay(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

/** "Oct 19, 2026" */
export function monthDayYear(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

/** "14 Oct 2026" (the template's `date:"d M Y"`). */
export function dayMonthYear(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return `${String(date.getDate()).padStart(2, "0")} ${date.toLocaleDateString("en-US", { month: "short" })} ${date.getFullYear()}`;
}

export function progressOf(c: Commitment) {
  const period = c.current_period;
  return {
    actual: period.accrued,
    target: period.target,
    percentage: period.percentage ?? 0,
    status: period.status ?? "behind",
    surplus: c.current_surplus,
  };
}

/** Where the old views sent you after a commitment write. */
export function redirectFor(c: Pick<Commitment, "aggregation_type" | "target">): string {
  return c.aggregation_type === "project" ? `/update_project/${c.target.id}/` : "/";
}

/** Today as yyyy-mm-dd in the profile's timezone (Django's `localdate`), falling back to the browser's. */
export function todayIn(timeZone: string | undefined): string {
  const now = new Date();
  try {
    return now.toLocaleDateString("en-CA", { timeZone });
  } catch {
    return now.toLocaleDateString("en-CA");
  }
}
