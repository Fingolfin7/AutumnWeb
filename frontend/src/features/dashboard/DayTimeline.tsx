import type { CSSProperties } from "react";
import { formatDuration, formatTime, formatDayDate } from "@/lib/format";
import { useNow } from "@/features/timers/api";
import type { Timer } from "@/api/types";
import type { Timeline, TimelineRange } from "./api";

const RANGES: { key: TimelineRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "d3", label: "3 days" },
  { key: "wk", label: "Week" },
];

const HOUR = 3_600_000;

/** The timer query owns live state; a persisted report must never resurrect
 * a stopped timer or omit one just started offline. Saved blocks stay intact. */
export function ledgerEntries(timeline: Timeline, running: Timer[], now: number) {
  const activeIds = new Set(running.map((timer) => timer.id));
  const dayStart = new Date(`${timeline.start_date}T00:00:00`).getTime();
  const lastDay = new Date(`${timeline.end_date}T00:00:00`);
  lastDay.setDate(lastDay.getDate() + 1);
  const dayEnd = lastDay.getTime();
  const saved = timeline.lanes.flatMap((lane) => lane.blocks
    .filter((block) => !block.is_live && !activeIds.has(block.session_id))
    .flatMap((block) => {
      const originalStart = Date.parse(block.start), originalEnd = Date.parse(block.end ?? block.start);
      const start = Math.max(originalStart, dayStart), end = Math.min(originalEnd, dayEnd);
      if (end <= start) return [];
      return [{ ...block, project: lane.project, start: new Date(start).toISOString(), end: new Date(end).toISOString(), minutes: block.minutes * (end - start) / (originalEnd - originalStart) }];
    }));
  const live = running.flatMap((timer) => {
    const start = Math.max(Date.parse(timer.start), dayStart);
    const end = Math.min(now, dayEnd);
    if (start > end) return [];
    return [
      {
        session_id: timer.id,
        project: timer.project,
        start: new Date(start).toISOString(),
        end: null,
        minutes: Math.max(0, end - start) / 60000,
        is_live: true,
        label: timer.subproject_allocations.map((sub) => sub.name).join(", "),
        note_html: null,
        start_pct: 0,
        end_pct: 0,
        width_pct: 0,
      },
    ];
  });
  return [...saved, ...live];
}

/** A window that starts and ends on round local hours, with at most six ticks. */
export function hourAxis(earliest: number, latest: number) {
  const step = [1, 2, 3, 4, 6, 12].find((hours) => Math.max(4, (latest - earliest) / HOUR) / hours <= 5) ?? 24;
  const round = (at: number) => {
    const date = new Date(at);
    date.setHours(date.getHours() - date.getHours() % step, 0, 0, 0);
    return date.getTime();
  };
  const from = round(earliest);
  let to = round(latest) + step * HOUR;
  while (to - from < 4 * HOUR) to += step * HOUR;
  const ticks: number[] = [];
  for (let at = from; at <= to; at += step * HOUR) ticks.push(at);
  return { from, to, ticks };
}

function midnights(from: number, to: number) {
  const ticks: number[] = [];
  const date = new Date(from);
  date.setHours(0, 0, 0, 0);
  if (date.getTime() < from) date.setDate(date.getDate() + 1);
  for (; date.getTime() <= to; date.setDate(date.getDate() + 1)) ticks.push(date.getTime());
  return ticks;
}

type Block = ReturnType<typeof ledgerEntries>[number];
const place = (at: number, span = 0) => ({ "--at": at, "--span": span }) as CSSProperties;

export function DayTimeline({ timeline, running, range, onRange }: {
  timeline: Timeline;
  running: Timer[];
  range: TimelineRange;
  onRange: (range: TimelineRange) => void;
}) {
  const now = useNow(30_000);
  const blocks = ledgerEntries(timeline, running, now);
  const lanes = [...new Map(blocks.map((block) => [block.project.id, block.project])).values()].map((project) => ({
    project,
    blocks: blocks.filter((block) => block.project.id === project.id),
  }));
  const total = blocks.reduce((sum, block) => sum + block.minutes, 0);
  const endOf = (block: Block) => block.is_live ? now : Date.parse(block.end ?? block.start);
  const { from, to, ticks } = range === "today"
    ? hourAxis(Math.min(now, ...blocks.map((block) => Date.parse(block.start))), Math.max(now, ...blocks.map(endOf)))
    : { from: Date.parse(timeline.window_start), to: Date.parse(timeline.window_end), ticks: midnights(Date.parse(timeline.window_start), Date.parse(timeline.window_end)) };
  const at = (time: number) => Math.max(0, Math.min(1, (time - from) / (to - from))) * 100;
  const nowVisible = now >= from && now <= to;

  const axis = (
    <div className="ledger-axis" aria-hidden="true">
      {ticks.filter((tick) => !nowVisible || Math.abs(at(tick) - at(now)) >= 14).map((tick) => (
        <span key={tick} className={at(tick) < 8 ? "is-start" : at(tick) > 92 ? "is-end" : undefined} style={place(at(tick))}>
          {range === "today" ? formatTime(new Date(tick)) : formatDayDate(new Date(tick)).split(" ")[0]}
        </span>
      ))}
      {nowVisible ? <span className={`ledger-now-label${at(now) < 8 ? " is-start" : at(now) > 92 ? " is-end" : ""}`} style={place(at(now))}>Now</span> : null}
    </div>
  );
  const rules = <>
    {ticks.map((tick) => <i className="ledger-grid" key={tick} style={place(at(tick))} />)}
    {nowVisible ? <i className="ledger-now" style={place(at(now))} /> : null}
  </>;
  const track = (items: Block[]) => (
    <div className="ledger-track">
      {rules}
      {items.map((block) => {
        const start = Date.parse(block.start);
        return <span
          key={`${block.session_id}-${block.start}`}
          className={`ledger-block${block.is_live ? " is-live" : ""}`}
          style={place(at(start), at(endOf(block)) - at(start))}
          title={`${block.project.name}${block.label ? ` / ${block.label}` : ""}: ${formatTime(block.start)}–${block.is_live ? "now" : formatTime(block.end)}`}
        />;
      })}
    </div>
  );
  const label = `${timeline.range_title}: ${formatDuration(total)}. Session details are in the journal.`;

  return (
    <section className="day-ledger" id="day-timeline" aria-label="Timeline">
      <header className="today-section-head">
        <h2>Your day<span className="ledger-voice">, taking shape</span></h2>
        <div className="range-tabs" role="tablist" aria-label="Timeline range">
          {RANGES.map((option) => (
            <button
              key={option.key}
              type="button"
              role="tab"
              aria-selected={range === option.key}
              className={`range-tab${range === option.key ? " is-active" : ""}`}
              onClick={() => onRange(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>
      {blocks.length ? (
        <>
          {timeline.is_multi_day ? <p className="ledger-range-total"><span className="ledger-total">{formatDuration(total)}</span> in this range</p> : null}
          <div className="day-ledger-chart" role="img" aria-label={label}>
            {axis}
            <div className="ledger-field">
              {lanes.map((lane) => (
                <div className="ledger-lane" key={lane.project.id}>
                  <p className="ledger-lane-label">
                    <span className="ledger-project" title={lane.project.name}>{lane.project.name}</span>
                    <span className="ledger-duration">{formatDuration(lane.blocks.reduce((sum, block) => sum + block.minutes, 0))}</span>
                  </p>
                  {track(lane.blocks)}
                </div>
              ))}
            </div>
          </div>
          <div className="day-ember-ribbon" role="img" aria-label={label}>
            {axis}
            {track(blocks)}
          </div>
        </>
      ) : (
        <p className="empty">An open day. Start a timer and see it take shape.</p>
      )}
    </section>
  );
}
