import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { faChevronLeft, faChevronRight, faPaperPlane, faSlidersH, faSyncAlt } from "@fortawesome/free-solid-svg-icons";
import { api, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { bootstrap } from "@/bootstrap";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { ErrorState, Skeleton } from "@/components/states";
import { formatDate, formatDuration } from "@/lib/format";
import { addDays, todayKey } from "@/features/notifications/dates";
import { semanticSearchAvailable, useChartData } from "@/features/charts/api";
import { ChartCanvas } from "@/features/charts/ChartCanvas";
import { buildChart, CHART_GROUPS, CIRCULAR_KINDS, parseKind } from "@/features/charts/build";
import { buildChartQuery, describeFilters, readFilters, writeFilters, type ChartFilters } from "@/features/charts/filters";
import type { DailyTotalRow, TallyRow } from "@/features/charts/payloads";
import { useCommitments } from "@/features/commitments/api";
import { ReviewFilters } from "./ReviewFilters";
import { YearOfEmbers } from "./YearOfEmbers";
import { WeekCard } from "./WeekCard";
import { comparisonPeriod, periodDays, presetPeriod, readPeriod, type Period, type Preset } from "./periods";

const PRESETS: { value: Preset; label: string }[] = [{ value: "today", label: "Today" }, { value: "week", label: "This week" }, { value: "last", label: "Last week" }, { value: "month", label: "30 days" }, { value: "custom", label: "Custom" }];
const totalOf = (rows: DailyTotalRow[]) => rows.reduce((sum, row) => sum + Number(row.hours) * 60, 0);
const deltaLabel = (now: number, before: number) => Math.abs(now - before) < 0.5 ? "Same time" : `${formatDuration(Math.abs(now - before))} ${now > before ? "more" : "less"}`;

export default function ReviewPage() {
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const { contextId } = useActiveContext();
  const profile = bootstrap().profile;
  const today = todayKey(profile.timezone);
  const period = readPeriod(params, today);
  const previous = comparisonPeriod(period);
  const [filterOpen, setFilterOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [chooserOpen, setChooserOpen] = useState(false);
  const [cardOpen, setCardOpen] = useState(false);
  const [year, setYear] = useState(Number(today.slice(0, 4)));
  const view = params.get("view") === "year" ? "year" : "period";
  const parsed = readFilters(params);
  const applied: ChartFilters = { ...parsed, search: params.get("search") ?? "", project_name: params.get("project_name") ?? "", projectMode: params.has("exclude_projects") ? parsed.projectMode : "include" };
  const effective = { ...applied, start_date: period.start, end_date: period.end };
  // Review defaults to direct, ranked rows; old chart links keep their kind.
  const kind = params.has("chart_type") ? applied.chart_type : "bar";
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const query = buildChartQuery(effective, {}, contextId);
  const current = useChartData({ ...query, chart_type: "bar" }, view === "period");
  const prior = useChartData({ ...query, chart_type: "bar", start_date: previous.start, end_date: previous.end }, view === "period");
  const daily = useChartData({ ...query, chart_type: "calendar" }, view === "period");
  const priorDaily = useChartData({ ...query, chart_type: "calendar", start_date: previous.start, end_date: previous.end }, view === "period");
  const annual = useChartData({ ...query, chart_type: "calendar", start_date: `${year}-01-01`, end_date: `${year}-12-31` }, true);
  const chart = useChartData({ ...query, chart_type: kind, ...(kind === "heatmap" ? { aggregate: true } : {}) }, view === "period" && kind !== "bar");
  const rows = [...((current.data?.data ?? []) as TallyRow[])].sort((a, b) => b.total_time - a.total_time);
  const priorRows = (prior.data?.data ?? []) as TallyRow[];
  const minutes = totalOf((daily.data?.data ?? []) as DailyTotalRow[]);
  const before = totalOf((priorDaily.data?.data ?? []) as DailyTotalRow[]);
  const loading = current.isPending || daily.isPending;
  const failed = current.isError || daily.isError;
  const built = useMemo(() => chart.data ? buildChart(kind, chart.data.data, { projectLimit: profile.default_chart_project_count || 7, subprojects: !!applied.project_name }) : null, [chart.data, kind, profile.default_chart_project_count, applied.project_name]);
  const pills = describeFilters({ ...applied, start_date: "", end_date: "" }, { projects: projects.data ?? [], tags: tags.data ?? [], contexts: contexts.data ?? [] }, { available: semanticSearchAvailable(), state: current.data?.related ?? annual.data?.related ?? null });

  const update = (next: ChartFilters) => {
    const value = writeFilters(next);
    if (params.has("chart_type")) value.set("chart_type", next.chart_type);
    if (view === "year") value.set("view", "year");
    setParams(value, { replace: true });
  };
  const setPeriod = (next: Period) => {
    const value = new URLSearchParams(params);
    value.set("start_date", next.start); value.set("end_date", next.end); value.delete("view");
    setParams(value); setCustomOpen(false);
  };
  const setView = (next: string) => { const value = new URLSearchParams(params); value.set("view", next); setParams(value); };
  const selectedPreset = PRESETS.find((preset) => { const value = presetPeriod(preset.value, today); return preset.value !== "custom" && value.start === period.start && value.end === period.end; })?.value ?? "custom";
  const rangeLabel = `${formatDate(period.start)} – ${formatDate(period.end, true)}`;
  const scope = query.context === "all" ? "All contexts" : contexts.data?.find((item) => String(item.id) === query.context)?.name ?? "Active context";
  const insightParams = writeFilters(view === "year" ? { ...effective, start_date: `${year}-01-01`, end_date: `${year}-12-31` } : effective); insightParams.delete("chart_type"); insightParams.set("context", query.context);
  const sessionParams = writeFilters(effective); sessionParams.delete("chart_type"); sessionParams.delete("project_name"); sessionParams.set("context", query.context);
  // The Sessions page accepts project IDs, not the chart's project-name field.
  if (effective.project_name) {
    const matching = (projects.data ?? []).filter((project) => project.name.toLowerCase().includes(effective.project_name.toLowerCase())).map((project) => project.id);
    const included = effective.projectMode === "include" && effective.projects.length ? matching.filter((id) => effective.projects.includes(id)) : matching.filter((id) => !effective.projects.includes(id));
    sessionParams.delete("include_projects"); sessionParams.delete("exclude_projects"); sessionParams.set("include_projects", included.length ? included.join(",") : "0");
  }
  const projectHref = (name: string) => {
    const value = new URLSearchParams(sessionParams);
    if (effective.project_name) return `${urls.sessions()}?${value}`;
    const ids = (projects.data ?? []).filter((project) => project.name === name
      && (query.context === "all" || String(project.context?.id) === query.context)
      && (applied.projectMode === "include" && applied.projects.length ? applied.projects.includes(project.id) : !applied.projects.includes(project.id))).map((project) => project.id);
    value.delete("exclude_projects"); value.delete("include_projects"); value.set("include_projects", ids.join(",") || "0");
    return `${urls.sessions()}?${value}`;
  };
  const shift = (direction: number) => setPeriod({ start: addDays(period.start, direction * periodDays(period)), end: addDays(period.end, direction * periodDays(period)) });
  const clearFilters = () => { const value = new URLSearchParams(); value.set("start_date", period.start); value.set("end_date", period.end); if (view === "year") value.set("view", "year"); setParams(value, { replace: true }); };
  const chartLabel = CHART_GROUPS.flatMap((group) => group.kinds).find((item) => item.value === kind)?.label ?? "Bar";

  if (projects.data?.length === 0) return <div className="review-desk">
    <h1 className="page-title">Review</h1>
    <section className="review-welcome slab">
      <h2>Your review starts with a session.</h2>
      <p>Save some time and come back to see where it went, how your weeks compare, and a year of little lights.</p>
      <AppLink className="btn btn--primary" href={urls.createProject()}>Create a project</AppLink>
    </section>
  </div>;

  return <div className="review-desk">
    <header className="review-heading"><div><h1 className="page-title">Review</h1><p className="muted">{scope} <span aria-hidden="true">·</span> Completed sessions</p></div><div className="review-heading-actions">{profile.insights_access_enabled ? <AppLink className="btn btn--secondary" href={`${urls.insights()}?${insightParams}`}>Ask about this</AppLink> : null}<button className="btn btn--quiet" type="button" onClick={() => setFilterOpen(true)}><Icon icon={faSlidersH} /> Filters{pills.length ? ` (${pills.length})` : ""}</button><button className="btn-icon" type="button" aria-label="Refresh review" onClick={() => { void client.invalidateQueries({ queryKey: ["reports"] }); void client.invalidateQueries({ queryKey: keys.commitments() }); }}><Icon icon={faSyncAlt} /></button></div></header>
    <div className="review-toolbar"><div className="review-view-switch" role="group" aria-label="Review view"><button type="button" aria-pressed={view === "period"} onClick={() => setView("period")}>Period</button><button type="button" aria-pressed={view === "year"} onClick={() => setView("year")}>Year of embers</button></div>{view === "period" ? <div className="review-presets" role="group" aria-label="Review period">{PRESETS.map((preset) => <button type="button" key={preset.value} aria-pressed={selectedPreset === preset.value} onClick={() => preset.value === "custom" ? setCustomOpen(true) : setPeriod(presetPeriod(preset.value, today))}>{preset.label}</button>)}</div> : null}</div>
    {pills.length ? <div className="filter-summary">{pills.map((pill) => <span className="filter-pill" title={pill.title} key={pill.label}>{pill.label} <b>{pill.value}</b></span>)}<button className="btn btn--quiet" type="button" onClick={clearFilters}>Clear filters</button></div> : null}
    {profile.insights_access_enabled ? <form className="review-question" onSubmit={(event) => {
      event.preventDefault();
      if (question.trim()) navigate(`${urls.insights()}?${insightParams}`, { state: { reviewQuestion: question.trim() } });
    }}>
      <label className="sr-only" htmlFor="review-question">Ask about this period</label>
      <input className="input" id="review-question" placeholder="Ask about this period…" value={question} onChange={(event) => setQuestion(event.target.value)} />
      <button className="btn btn--quiet" aria-label="Send period question" disabled={!question.trim()}><Icon icon={faPaperPlane} /></button>
    </form> : null}

    {view === "period" ? <>
      <section className="review-period slab" aria-label="Period summary">
        <div className="review-range"><button className="btn-icon" type="button" aria-label="Previous period" onClick={() => shift(-1)}><Icon icon={faChevronLeft} /></button><h2>{rangeLabel}</h2><button className="btn-icon" type="button" aria-label="Next period" disabled={period.end >= today} onClick={() => shift(1)}><Icon icon={faChevronRight} /></button></div>
        {loading ? <Skeleton lines={2} /> : failed ? <ErrorState error={current.error ?? daily.error} onRetry={() => { void current.refetch(); void daily.refetch(); }} /> : <div className="review-total-row"><div><strong className="review-total">{formatDuration(minutes)}</strong><p className="review-comparison" aria-live="polite">{priorDaily.isError ? "Previous period unavailable" : priorDaily.isPending ? "Comparing periods…" : <><b>{deltaLabel(minutes, before)}</b> than {formatDate(previous.start)}{previous.end !== previous.start ? ` – ${formatDate(previous.end)}` : ""}{period.end > today ? " · period in progress" : ""}</>}</p></div><AppLink className="btn btn--quiet" href={`${urls.sessions()}?${sessionParams}`}>Browse sessions</AppLink></div>}
        {!loading && !failed && minutes > 0 && periodDays(period) <= 62 ? <div className="review-day-strip" aria-label="Daily time in selected period">{Array.from({ length: Math.min(periodDays(period), 62) }, (_, index) => { const day = addDays(period.start, index); const value = ((daily.data?.data ?? []) as DailyTotalRow[]).find((item) => item.date === day); return <div key={day} title={`${formatDate(day)}: ${formatDuration(Number(value?.hours ?? 0) * 60)}`}><svg viewBox="0 0 12 50" aria-hidden="true"><rect x="2" y={48 - Math.min(46, Number(value?.hours ?? 0) * 8)} width="8" height={Math.max(2, Math.min(46, Number(value?.hours ?? 0) * 8))} rx="3" /></svg><span>{periodDays(period) <= 7 ? new Date(`${day}T12:00Z`).toLocaleDateString("en", { weekday: "short", timeZone: "UTC" }) : index % 7 === 0 ? day.slice(-2) : ""}</span></div>; })}</div> : null}
      </section>

      <div className="review-body"><section className={`review-projects slab${applied.project_name ? " review-projects--subprojects" : ""}`} aria-labelledby="review-projects-title"><div className="review-section-heading"><h2 id="review-projects-title">{applied.project_name ? "Inside the project" : "Where the time went"}</h2><button type="button" className="btn btn--quiet" onClick={() => setChooserOpen(true)}>Chart: {chartLabel}</button></div>
        {loading ? <Skeleton lines={4} /> : failed ? null : !rows.length ? <p className="review-empty">No completed sessions in this period. Choose another range, or <AppLink href={urls.startTimer()}>start a timer</AppLink>.</p> : kind === "bar" ? <div className="review-rankings">{rows.map((row) => { const old = priorRows.find((item) => item.name === row.name)?.total_time ?? 0; return <AppLink className="review-project-row" href={projectHref(row.name)} key={row.name}><span className="review-project-name">{row.name}</span><strong>{formatDuration(row.total_time)}</strong><svg className="review-project-bar" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="4" rx="2" className="review-bar-track" /><rect width={100 * row.total_time / Math.max(rows[0]?.total_time ?? 1, 1)} height="4" rx="2" /></svg><small>{prior.isError ? "Comparison unavailable" : prior.isPending ? "Comparing…" : deltaLabel(row.total_time, old)}</small></AppLink>; })}</div> : <section id="chart_section" className="review-chart">{chart.isPending ? <Skeleton lines={4} /> : chart.isError ? <ErrorState error={chart.error} onRetry={() => void chart.refetch()} /> : built ? <div id="canvas_container" className={CIRCULAR_KINDS.includes(kind) ? "chart-circular" : undefined}><ChartCanvas built={built} /></div> : <p className="review-empty">Nothing to chart for this selection.</p>}</section>}
        {rows.length > 0 ? <div className="review-project-foot"><span className="muted">{rows.length} {applied.project_name ? "subproject" : "project"}{rows.length === 1 ? "" : "s"} · Choose a row to read its sessions</span><button className="btn btn--quiet" type="button" onClick={() => setCardOpen(true)}>Save a card</button></div> : null}
      </section><ReviewCommitments start={period.start} /></div>
    </> : null}

    <section className={`review-embers slab${view === "year" ? " review-embers--hero" : ""}`} aria-labelledby="ember-title"><div className="review-section-heading"><div><h2 id="ember-title">A year of embers</h2><p className="muted">{scope}{pills.length ? " · current filters" : ""} · Daily totals grouped by UTC date</p></div><div className="review-year-stepper"><button className="btn-icon" aria-label="Previous year" type="button" onClick={() => setYear(year - 1)}><Icon icon={faChevronLeft} /></button><strong>{year}</strong><button className="btn-icon" aria-label="Next year" type="button" disabled={year >= Number(today.slice(0, 4))} onClick={() => setYear(year + 1)}><Icon icon={faChevronRight} /></button></div></div>{annual.isPending ? <Skeleton lines={4} /> : annual.isError ? <ErrorState error={annual.error} onRetry={() => void annual.refetch()} /> : <YearOfEmbers year={year} rows={(annual.data?.data ?? []) as DailyTotalRow[]} onMonth={setPeriod} />}</section>

    <ReviewFilters open={filterOpen} onClose={() => setFilterOpen(false)} draft={effective} onChange={update} onClear={clearFilters} />
    <Sheet open={customOpen} onClose={() => setCustomOpen(false)} title="Custom range"><div className="fields"><p className="muted">Your review updates as you change the dates.</p><div className="field"><label htmlFor="start_date">Start date</label><input id="start_date" type="date" value={applied.start_date || period.start} max={applied.end_date || undefined} onChange={(event) => { if (event.target.value) update({ ...effective, start_date: event.target.value }); }} /></div><div className="field"><label htmlFor="end_date">End date</label><input id="end_date" type="date" min={applied.start_date || period.start} value={applied.end_date || period.end} onChange={(event) => { if (event.target.value) update({ ...effective, end_date: event.target.value }); }} /></div><button type="button" className="btn btn--secondary" onClick={() => setCustomOpen(false)}>Done</button></div></Sheet>
    <Sheet open={chooserOpen} onClose={() => setChooserOpen(false)} title="Choose a chart"><div className="review-chart-chooser">{CHART_GROUPS.map((group) => <div key={group.label}><h3>{group.label}</h3>{group.kinds.map((option) => <button className="review-chart-choice" key={option.value} type="button" aria-pressed={kind === option.value} onClick={() => { const value = new URLSearchParams(params); value.set("chart_type", parseKind(option.value)); setParams(value, { replace: true }); setChooserOpen(false); }}>{option.value === "bar" ? "Ranked project bars" : option.label}<span>{option.value === "bar" ? "Compare projects at a glance" : ""}</span></button>)}</div>)}</div></Sheet>
    <WeekCard open={cardOpen} onClose={() => setCardOpen(false)} period={period} minutes={minutes} rows={rows} />
  </div>;
}

function ReviewCommitments({ start }: { start: string }) {
  const commitments = useCommitments();
  const [historyOpen, setHistoryOpen] = useState(false);
  const history = useQuery({ enabled: historyOpen && commitments.isSuccess, queryKey: keys.reports("weekly-review", { week: start }), queryFn: () => unwrap(api.GET("/api/v2/reports/weekly-review/", { params: { query: { week: start } } })) });
  return <section className="review-commitments slab" aria-labelledby="review-commitments-title"><div className="review-section-heading"><div><h2 id="review-commitments-title">Commitments</h2><p className="muted">Current periods · all contexts</p></div></div>
    {commitments.isPending ? <Skeleton lines={3} /> : commitments.isError ? <ErrorState error={commitments.error} onRetry={() => void commitments.refetch()} /> : !commitments.data?.some((item) => item.active) ? <p className="review-empty">A little structure for what matters. <AppLink href={urls.createCommitment()}>Set a commitment</AppLink>.</p> : commitments.data.filter((item) => item.active).map((item) => {
      const current = item.current_period;
      const amount = (value: number) => item.commitment_type === "time" ? formatDuration(value) : `${Math.round(value)} session${Math.round(value) === 1 ? "" : "s"}`;
      const left = Math.max(0, current.target - current.accrued);
      return <article className="review-commitment" key={item.id}><AppLink href={urls.updateCommitment(item.id)}>{item.target.name}</AppLink><p><b>{amount(current.accrued)}</b> of {amount(current.target)} this {{ daily: "day", weekly: "week", fortnightly: "fortnight", monthly: "month", quarterly: "quarter", yearly: "year" }[item.period]}</p><p className="muted">{current.met ? "Target met" : `${amount(left)} left`} · resets {formatDate(current.end)}</p><progress max={Math.max(1, current.target)} value={Math.min(current.accrued, current.target)} aria-label={`${item.target.name} progress`} /><details><summary>Banking & details</summary><p>{item.banking_enabled ? `${amount(Math.abs(item.balance))} ${item.balance < 0 ? "owed" : "banked"}` : "Banking is off"}. <AppLink href={urls.updateCommitment(item.id)}>Edit commitment</AppLink></p>{item.pending_revision ? <p>Change scheduled from {formatDate(item.pending_revision.effective_from)}.</p> : null}</details></article>;
    })}
    <details className="review-closed-periods" onToggle={(event) => setHistoryOpen(event.currentTarget.open)}><summary>Closed commitment periods</summary><p className="muted">{formatDate(start)} – {formatDate(addDays(start, 6))} · all contexts, independent of review filters</p>{history.isPending ? <p>Loading closed periods…</p> : history.isError ? <ErrorState error={history.error} onRetry={() => void history.refetch()} /> : <><p>{history.data.met_count} of {history.data.eligible_count} commitments met</p>{history.data.details.map((item) => <p key={item.commitment_id}><AppLink href={urls.updateCommitment(item.commitment_id)}>{item.target_name}</AppLink> · {item.met_period_count} of {item.period_count} periods met</p>)}</>}</details>
  </section>;
}
