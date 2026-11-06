import { formatDuration, formatDate } from "@/lib/format";
import { addDays } from "@/features/notifications/dates";
import type { DailyTotalRow } from "@/features/charts/payloads";
import type { Period } from "./periods";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function YearOfEmbers({ year, rows, onMonth }: { year: number; rows: DailyTotalRow[]; onMonth: (period: Period) => void }) {
  const totals = new Map(rows.map((row) => [row.date, Number(row.hours) * 60]));
  const active = [...totals.values()].filter((value) => value > 0).length;
  const minutes = [...totals.values()].reduce((sum, value) => sum + value, 0);
  return <>
    <div className="ember-intro"><p>Every day leaves a little light.</p><span><b className="text-green">{formatDuration(minutes)}</b> across {active} active days</span></div>
    <div className="ember-year">
      {MONTHS.map((month, index) => {
        const start = `${year}-${String(index + 1).padStart(2, "0")}-01`;
        const end = addDays(index === 11 ? `${year + 1}-01-01` : `${year}-${String(index + 2).padStart(2, "0")}-01`, -1);
        const days = Number(end.slice(-2));
        const offset = (new Date(`${start}T12:00:00Z`).getUTCDay() + 6) % 7;
        const total = Array.from({ length: days }, (_, day) => totals.get(addDays(start, day)) ?? 0).reduce((sum, value) => sum + value, 0);
        return <button type="button" className="ember-month" key={month} onClick={() => onMonth({ start, end })} aria-label={`${month} ${year}, ${formatDuration(total)}. Review this month`}>
          <span className="ember-month-name">{month.slice(0, 3)}</span>
          <svg viewBox="0 0 82 70" aria-hidden="true">
            {Array.from({ length: days }, (_, day) => {
              const key = addDays(start, day);
              const value = totals.get(key) ?? 0;
              const level = !value ? 0 : value < 30 ? 1 : value < 60 ? 2 : value < 120 ? 3 : value < 240 ? 4 : 5;
              return <rect key={day} x={((offset + day) % 7) * 12} y={Math.floor((offset + day) / 7) * 12} width="9" height="9" rx="2" className={`ember-cell ember-cell--${level}`}><title>{formatDate(key)}: {formatDuration(value)}</title></rect>;
            })}
          </svg>
          <span className="ember-month-total">{total ? formatDuration(total) : "—"}</span>
        </button>;
      })}
    </div>
    <div className="ember-key"><span>Quiet</span>{[0, 1, 2, 3, 4, 5].map((level) => <svg key={level} width="12" height="12" aria-hidden="true"><rect width="12" height="12" rx="3" className={`ember-cell ember-cell--${level}`} /></svg>)}<span>4h+</span><span className="ember-key-hint">Choose a month to explore</span></div>
  </>;
}
