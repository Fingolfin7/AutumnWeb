import { formatDate } from "@/lib/format";
import type { Commitment } from "@/api/types";

/* Number and date display shared by the commitment pages. */

export const monthDay = (value: string | Date) => formatDate(value);
export const monthDayYear = (value: string | Date) => formatDate(value, true);
export const dayMonthYear = monthDayYear;

export function hasPendingChange(commitment: Commitment) {
  return !!commitment.pending_revision && Object.keys(commitment.pending_revision.changes).length > 0;
}

/** Restoring the live definition cancels queued edits through the existing API. */
export function liveDefinition(commitment: Commitment) {
  return { target_value: commitment.target_value, banking_enabled: commitment.banking_enabled, max_balance: commitment.max_balance, min_balance: commitment.min_balance, ...commitment.filters };
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
