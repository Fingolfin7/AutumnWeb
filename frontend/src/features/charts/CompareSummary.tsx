import { parseDay, type Range } from "./data";
import type { DailyTotalRow } from "./payloads";

export function totalHours(rows: unknown): number {
  return Array.isArray(rows) ? (rows as DailyTotalRow[]).reduce((sum, row) => sum + Number(row.hours), 0) : 0;
}

const hours = (value: number) => `${value.toFixed(1)} h`;
const day = (value: string, year: boolean) =>
  parseDay(value).toLocaleDateString(undefined, { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}) });

/* The period total and its change against the previous period. The change
   stays in neutral ink: more hours is not better or worse by itself. */
export function CompareSummary({ now, previous, previousRange, note }: { now: number | null; previous: number | null; previousRange: Range; note?: string }) {
  if (now === null || previous === null) return <p className="chart-compare muted">Comparing with the previous period…</p>;
  const change = now - previous;
  const percent = previous > 0 ? Math.round((change / previous) * 100) : null;
  const sameYear = previousRange.start.slice(0, 4) === previousRange.end.slice(0, 4);
  return (
    <div className="chart-compare" role="status">
      <p className="chart-compare-total">
        <span className="mono">{hours(now)}</span> this period
      </p>
      <p className="chart-compare-change">
        <span className="mono">
          {Math.abs(change) < 0.05 ? "No change" : `${change > 0 ? "▲ +" : "▼ −"}${hours(Math.abs(change))}${percent === null ? "" : ` (${change > 0 ? "+" : "−"}${Math.abs(percent)}%)`}`}
        </span>{" "}
        vs <span className="mono">{hours(previous)}</span> in {day(previousRange.start, !sameYear)} – {day(previousRange.end, true)}
        {note ? <span className="chart-compare-key"> · {note}</span> : null}
      </p>
    </div>
  );
}
