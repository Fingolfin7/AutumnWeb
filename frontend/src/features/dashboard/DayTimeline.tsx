import type { CSSProperties } from "react";
import { AppLink, urls } from "@/app/links";
import { formatDuration, formatTime, parseInstant } from "@/lib/format";
import { useNow } from "@/features/timers/api";
import type { Timeline, TimelineRange } from "./api";

const RANGES: { key: TimelineRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "d3", label: "3 days" },
  { key: "wk", label: "Week" },
];

type Vars = CSSProperties & Record<`--${string}`, string>;

const pad = (n: number) => String(n).padStart(2, "0");
function compactMinutes(minutes: number) {
  const whole = Math.round(minutes);
  const hours = Math.floor(whole / 60);
  return hours ? `${hours}h ${pad(whole % 60)}m` : `${whole % 60}m`;
}

/* The day timeline (partials/day_timeline.html). The server draws the
   geometry; between fetches the live blocks and the now-marker are walked
   forward here every 30 s, mapping the same absolute window onto 0-100%. */
export function DayTimeline({
  timeline,
  range,
  onRange,
}: {
  timeline: Timeline;
  range: TimelineRange;
  onRange: (range: TimelineRange) => void;
}) {
  const now = useNow(30_000);
  const windowStart = Date.parse(timeline.window_start);
  const windowEnd = Date.parse(timeline.window_end);
  const valid = !Number.isNaN(windowStart) && !Number.isNaN(windowEnd) && windowEnd > windowStart;
  const pct = (stamp: number) => Math.max(0, Math.min(100, ((stamp - windowStart) / (windowEnd - windowStart)) * 100));
  const nowInWindow = valid && now >= windowStart && now <= windowEnd;

  return (
    <section className="slab fd-tl-slab" id="day-timeline" aria-label="Timeline">
      <header className="fd-tl-head">
        <p className="fd-tl-total" title={timeline.range_title}>
          <span className="fd-tl-total-label">Tracked{timeline.is_multi_day ? "" : " today"}</span>{" "}
          {formatDuration(timeline.tracked_minutes)}
        </p>
        <div className="range-tabs" role="tablist" aria-label="Timeline range">
          {RANGES.map((option) => (
            <button
              key={option.key}
              className={`range-tab${range === option.key ? " is-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={range === option.key}
              onClick={() => onRange(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>
      <div className="fd-tl" style={{ "--tick": `${timeline.grid_pct}%` } as Vars}>
        <div className="fd-tl-axis" aria-hidden="true">
          {timeline.ticks.map((tick) => (
            <span
              key={`${tick.x_pct}-${tick.label}`}
              className={`fd-tl-lab${tick.minor ? " fd-tl-lab--minor" : ""}`}
              style={{ "--x": `${tick.x_pct}%` } as Vars}
            >
              {tick.label}
            </span>
          ))}
        </div>
        {timeline.lanes.length ? (
          <div className="fd-tl-plot">
            {timeline.lanes.map((lane) => (
              <div className="fd-tl-lane" key={lane.project.id} style={{ "--proj": lane.colour } as Vars}>
                <div className="fd-tl-head-cell">
                  <AppLink className="fd-tl-name" href={urls.updateProject(lane.project.id)}>
                    {lane.project.name}
                  </AppLink>
                  <span className="fd-tl-fig">
                    {lane.total_label ?? ""}
                    {lane.live_label ? (
                      <span className="muted">
                        {lane.total_label ? " + " : ""}
                        {lane.live_label} live
                      </span>
                    ) : null}
                  </span>
                </div>
                <div className="fd-tl-track">
                  {lane.blocks.map((block) => {
                    let start = block.start_pct;
                    let end = block.end_pct;
                    let width = block.width_pct;
                    let durationLabel = block.duration_label;
                    if (block.is_live && valid) {
                      const started = parseInstant(block.start)?.getTime();
                      if (started !== undefined) {
                        const from = Math.max(started, windowStart);
                        start = pct(from);
                        end = pct(now);
                        width = Math.max(0, end - start);
                        durationLabel = compactMinutes((now - from) / 60000);
                      }
                    }
                    const label = `${lane.project.name}${block.label ? `, ${block.label}` : ""}, ${durationLabel}${block.is_live ? ", running" : ""}`;
                    return (
                      <div
                        className="fd-tl-mark"
                        key={`${block.session_id}-${block.start}`}
                        style={{ "--start": `${start.toFixed(4)}%`, "--w": `${width.toFixed(4)}%`, "--end": `${end.toFixed(4)}%` } as Vars}
                      >
                        <div
                          className={`fd-tl-block${block.is_live ? " is-live" : ""}${block.start_pct > 85 ? " is-endflip" : ""}`}
                          tabIndex={0}
                          aria-label={label}
                        >
                          <span className="fd-tl-b-text">
                            {block.label ? <span className="fd-tl-b-lab">{block.label}</span> : null}
                            <span className="fd-tl-b-dur">{durationLabel}</span>
                          </span>
                        </div>
                        <div className={`fd-tl-tip${block.start_pct > 55 ? " fd-tl-tip--flip" : ""}`}>
                          <p>
                            <span className="mono text-cyan">
                              {formatTime(block.start)} &rarr; {block.is_live ? "running" : formatTime(block.end)}
                            </span>{" "}
                            <span className="mono text-green">{durationLabel}</span>
                          </p>
                          <p>
                            <span className="text-red">{lane.project.name}</span>{" "}
                            {block.label ? <span className="text-blue">[{block.label}]</span> : null}
                          </p>
                          {block.note_html ? (
                            <div className="fd-tl-tip-note" dangerouslySetInnerHTML={{ __html: block.note_html }} />
                          ) : null}
                          <AppLink className="fd-tl-tip-link" href={urls.updateSession(block.session_id)}>
                            Edit session
                          </AppLink>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            <div className="fd-tl-nowlayer" aria-hidden="true">
              {timeline.now_label !== null && nowInWindow ? (
                <div className="fd-tl-now" style={{ "--x": `${pct(now).toFixed(4)}%` } as Vars}>
                  <span className="fd-tl-now-flag mono">{formatTime(new Date(now), false)}</span>
                </div>
              ) : null}
              {timeline.gaps.map((gap) => (
                <div
                  className="fd-tl-gap"
                  key={`${gap.start_pct}`}
                  style={{ "--start": `${gap.start_pct}%`, "--w": `${gap.width_pct}%` } as Vars}
                >
                  <span>{gap.label}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="fd-tl-empty">
            {timeline.is_multi_day ? "Nothing tracked in this range." : "Nothing tracked today yet."}{" "}
            <AppLink href={urls.startTimer()}>Start a timer</AppLink> and this fills in as you go.
          </p>
        )}
      </div>
    </section>
  );
}
