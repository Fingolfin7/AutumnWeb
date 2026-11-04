import { AppLink, urls } from "@/app/links";
import { formatDuration, formatTime, formatDayDate } from "@/lib/format";
import { useNow } from "@/features/timers/api";
import type { Timer } from "@/api/types";
import type { Timeline, TimelineRange } from "./api";

const RANGES: { key: TimelineRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "d3", label: "3 days" },
  { key: "wk", label: "Week" },
];

/** The timer query owns live state; a persisted report must never resurrect
 * a stopped timer or omit one just started offline. Saved blocks stay intact. */
export function ledgerEntries(timeline: Timeline, running: Timer[], now: number) {
  const activeIds = new Set(running.map((timer) => timer.id));
  const saved = timeline.lanes.flatMap((lane) =>
    lane.blocks
      .filter((block) => !block.is_live && !activeIds.has(block.session_id))
      .map((block) => ({ ...block, project: lane.project })),
  );
  const dayStart = new Date(`${timeline.start_date}T00:00:00`).getTime();
  const lastDay = new Date(`${timeline.end_date}T00:00:00`);
  lastDay.setDate(lastDay.getDate() + 1);
  const dayEnd = lastDay.getTime();
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

export function DayTimeline({
  timeline,
  running,
  range,
  onRange,
}: {
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
  const ordered = [...blocks].sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  const liveMinutes = blocks.filter((block) => block.is_live).reduce((sum, block) => sum + block.minutes, 0);
  const total = blocks.reduce((sum, block) => sum + block.minutes, 0);
  const hour = 3600000;
  const earliest = Math.min(now, ...blocks.map((b) => Date.parse(b.start)));
  const latest = Math.max(now, ...blocks.map((b) => (b.is_live ? now : Date.parse(b.end ?? b.start))));
  const from = range === "today" ? Math.floor(earliest / hour) * hour : Date.parse(timeline.window_start);
  const to =
    range === "today"
      ? Math.max(from + 4 * hour, Math.ceil(latest / hour) * hour + hour)
      : Date.parse(timeline.window_end);
  const x = (at: number) => 240 + Math.max(0, Math.min(1, (at - from) / (to - from))) * 740;
  const ticks = Array.from({ length: 5 }, (_, i) => from + ((to - from) * i) / 4);
  return (
    <section className="day-ledger" id="day-timeline" aria-label="Timeline">
      <header className="today-section-head">
        <div>
          <h2>Your day, taking shape</h2>
          <p>
            <span className="text-green ledger-total">{formatDuration(total)}</span>{" "}
            <span className="muted">
              {timeline.is_multi_day ? "in this range" : "today"}
              {liveMinutes > 0 ? ", including live time" : ""}
            </span>
          </p>
        </div>
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
          <svg
            className="day-ledger-chart"
            viewBox={`0 0 1000 ${76 + lanes.length * 82}`}
            role="img"
            aria-label={`${timeline.range_title}: ${formatDuration(total)}. Session details follow.`}
          >
            <defs>
              <linearGradient id="ledger-ember">
                <stop stopColor="#ad5734" />
                <stop offset="1" stopColor="#eda45d" />
              </linearGradient>
            </defs>
            {ticks.map((at) => (
              <g key={at}>
                <text x={x(at)} y={24} textAnchor="middle" className="ledger-axis">
                  {range === "today" ? formatTime(new Date(at)) : formatDayDate(new Date(at))}
                </text>
                <line x1={x(at)} x2={x(at)} y1={40} y2={60 + lanes.length * 82} className="ledger-grid" />
              </g>
            ))}
            {lanes.map((lane, index) => (
              <g key={lane.project.id}>
                <text x={0} y={72 + index * 82} className="ledger-project">
                  {lane.project.name.length > 27 ? `${lane.project.name.slice(0, 26)}...` : lane.project.name}
                  <title>{lane.project.name}</title>
                </text>
                <text x={0} y={95 + index * 82} className="ledger-duration">
                  {formatDuration(
                    lane.blocks.reduce(
                      (sum, b) =>
                        sum + (b.is_live ? Math.max(0, now - Math.max(from, Date.parse(b.start))) / 60000 : b.minutes),
                      0,
                    ),
                  )}
                </text>
                {lane.blocks.map((b) => (
                  <g key={`${b.session_id}-${b.start}`}>
                    <rect
                      x={x(Date.parse(b.start))}
                      y={56 + index * 82}
                      width={Math.max(5, x(b.is_live ? now : Date.parse(b.end ?? b.start)) - x(Date.parse(b.start)))}
                      height={42}
                      rx={5}
                      className={b.is_live ? "ledger-block is-live" : "ledger-block"}
                    >
                      <title>
                        {lane.project.name}
                        {b.label ? ` / ${b.label}` : ""}: {formatTime(b.start)}–{b.is_live ? "now" : formatTime(b.end)}
                      </title>
                    </rect>
                  </g>
                ))}
              </g>
            ))}
            {now >= from && now <= to ? (
              <g>
                <line x1={x(now)} x2={x(now)} y1={38} y2={65 + lanes.length * 82} className="ledger-now" />
                <circle cx={x(now)} cy={38} r={4} className="ledger-now-dot" />
              </g>
            ) : null}
          </svg>
          <ol className="day-ledger-entries">
            {ordered.map((b) => (
              <li key={`${b.session_id}-${b.start}`} className={b.is_live ? "is-live" : ""}>
                <div className="ledger-entry-time">
                  <time>
                    {range === "today" ? formatTime(b.start) : `${formatDayDate(b.start)} ${formatTime(b.start)}`}
                  </time>
                  <span>{b.is_live ? "Now" : formatTime(b.end)}</span>
                </div>
                <AppLink
                  href={b.is_live ? urls.home() : urls.updateSession(b.session_id)}
                  className="ledger-entry-project"
                >
                  <span className="text-red">{b.project.name}</span>
                  {b.label ? <small className="text-blue">{b.label}</small> : null}
                </AppLink>
                <span className="text-green">
                  {formatDuration(b.is_live ? Math.max(0, now - Date.parse(b.start)) / 60000 : b.minutes)}
                  {b.is_live ? <small className="ledger-live-label">Live</small> : null}
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className="empty">An open day. Start a timer and see it take shape.</p>
      )}
    </section>
  );
}
