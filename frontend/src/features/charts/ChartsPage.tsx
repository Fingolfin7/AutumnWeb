import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { faCalendarAlt, faSlidersH, faSyncAlt } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { OptionPicker } from "@/components/OptionPicker";
import { Sheet } from "@/components/Sheet";
import { ErrorState } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { bootstrap } from "@/bootstrap";
import { ChartCanvas } from "./ChartCanvas";
import { semanticSearchAvailable, useChartData } from "./api";
import { buildChart, CHART_GROUPS, CIRCULAR_KINDS, COMPARE, NO_COMPARE, parseKind, valueExtent } from "./build";
import { CompareSummary, rangeLabel, totalHours } from "./CompareSummary";
import { periodDays, previousRange } from "./data";
import { buildChartQuery, describeFilters, EMPTY_FILTERS, readFilters, writeFilters, type ChartFilters, type ChartQuery } from "./filters";
import { SimilaritySlider } from "@/features/search/SimilaritySlider";
import { accountSimilarity, sameCutoff, similarityScale } from "@/features/search/similarity";

export default function ChartsPage() {
  const [params, setParams] = useSearchParams();
  const applied = useMemo(() => readFilters(params), [params]);
  const { contextId } = useActiveContext();
  const queryClient = useQueryClient();
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const [sheetOpen, setSheetOpen] = useState(false);

  /* The range opens on the profile's default filter (computed by the server,
     in the profile's timezone), so the fields read as "this is the window"
     rather than as an empty form. */
  const { default_chart_start_date: defaultStart, default_chart_end_date: defaultEnd } = bootstrap().profile;
  const defaults = useMemo(() => ({ start: defaultStart, end: defaultEnd }), [defaultStart, defaultEnd]);

  const effective: ChartFilters = useMemo(
    () => ({ ...applied, start_date: applied.start_date || defaults.start, end_date: applied.end_date || defaults.end }),
    [applied, defaults],
  );

  /* Edits wait for Apply; the chart type is the exception and redraws at
     once. The draft follows the URL whenever the filters in it change. */
  const [draft, setDraft] = useState<ChartFilters>(effective);
  const filtersKey = writeFilters({ ...effective, chart_type: EMPTY_FILTERS.chart_type, compare: false }).toString();
  useEffect(() => setDraft((current) => ({ ...effective, chart_type: current.chart_type, compare: current.compare })), [filtersKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const semantic = semanticSearchAvailable();
  const query = useMemo(() => buildChartQuery(applied, defaults, contextId), [applied, defaults, contextId]);
  const chart = useChartData(query, true);
  const kind = applied.chart_type;

  /* Comparing asks the same endpoint again for the window of equal length
     just before, every other filter unchanged: daily totals of both windows
     for the summary, and the chart's own payload for the previous window.
     Kinds without a comparison keep ?compare=on in the URL but ignore it. */
  const range = query.start_date && query.end_date ? { start: query.start_date, end: query.end_date } : undefined;
  const compare = COMPARE[kind];
  const before = applied.compare && range && compare ? previousRange(range) : null;
  const shifted = (base: ChartQuery) => ({ ...base, start_date: before?.start, end_date: before?.end });
  const totalsQuery: ChartQuery = { ...query, chart_type: "calendar", aggregate: undefined };
  const previousChart = useChartData(shifted(query), !!before);
  const totals = useChartData(totalsQuery, !!before);
  const previousTotals = useChartData(shifted(totalsQuery), !!before);

  /* One chart, or with a "panels" comparison one per period, on one shared
     scale (an empty previous period still gets its panel, drawn empty). */
  const panels = useMemo((): { built: ReturnType<typeof buildChart>; label?: string }[] | null => {
    if (!chart.data) return null;
    const options = { projectLimit: bootstrap().profile.default_chart_project_count || 7, subprojects: !!applied.project_name, range };
    const previous = before ? previousChart.data?.data : undefined;
    if (compare?.draw !== "panels" || !before || !range) return [{ built: buildChart(kind, chart.data.data, { ...options, previous }) }];
    if (previous === undefined) return [];
    const [lo1, hi1] = valueExtent(kind, chart.data.data);
    const [lo2, hi2] = valueExtent(kind, previous);
    const extent: [number, number] = [Math.min(lo1, lo2), Math.max(hi1, hi2)];
    return [
      { built: buildChart(kind, chart.data.data, { ...options, extent }), label: `This period · ${rangeLabel(range)}` },
      { built: buildChart(kind, previous, { ...options, range: before, extent }), label: `Previous period · ${rangeLabel(before)}` },
    ];
  }, [chart.data, kind, applied.project_name, range?.start, range?.end, before?.start, previousChart.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const built = panels?.[0]?.built ?? null;

  const pills = describeFilters(
    applied,
    { projects: projects.data ?? [], tags: tags.data ?? [], contexts: contexts.data ?? [] },
    { available: semantic, state: chart.data?.related ?? null },
  );

  const apply = (state: ChartFilters) => {
    setParams(writeFilters(state));
    setSheetOpen(false);
  };
  const onApply = (event: FormEvent) => {
    event.preventDefault();
    apply(draft);
  };
  const pickKind = (value: string) => {
    const next = parseKind(value);
    setDraft((current) => ({ ...current, chart_type: next }));
    /* No history entry: Back should leave the page, not step through types. */
    setParams(writeFilters({ ...applied, chart_type: next }), { replace: true });
  };
  const toggleCompare = (compare: boolean) => {
    setDraft((current) => ({ ...current, compare }));
    setParams(writeFilters({ ...applied, compare }), { replace: true });
  };

  /* The project picker narrows itself to the context and tags chosen beside
     it (option_pickers.js, EXCLUDE_PROJECT_META); a ticked project always
     stays visible. */
  const projectOptions = useMemo(() => {
    const scopeContext = draft.context === "all" ? null : draft.context ? Number(draft.context) : contextId;
    return (projects.data ?? [])
      .filter((project) => {
        if (draft.projects.includes(project.id)) return true;
        if (scopeContext !== null && project.context?.id !== scopeContext) return false;
        if (draft.tags.length && !project.tags.some((tag) => draft.tags.includes(tag.id))) return false;
        return true;
      })
      .map((project) => ({ id: project.id, label: project.name }));
  }, [projects.data, draft.context, draft.tags, draft.projects, contextId]);

  /* Offline with nothing saved for these filters: the request waits for a
     connection, so say that rather than load forever. */
  const waitingOffline = chart.isPending && chart.isPaused;
  const loading = !waitingOffline && (chart.isPending || chart.isFetching || (!!before && previousChart.isPending && !previousChart.isPaused));
  const empty = !loading && !waitingOffline && !chart.isError && !built;

  return (
    <>
      <h1 className="sr-only">Charts</h1>
      <form className="fields" id="search_form" onSubmit={onApply}>
        <div className="searchbar searchbar--range">
          <Icon icon={faCalendarAlt} className="fas muted" />
          <span className="range-fields">
            <label className="sr-only" htmlFor="start_date">
              Start date
            </label>
            <input id="start_date" type="date" value={draft.start_date} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} />
            <span className="range-sep muted" aria-hidden="true">
              &rarr;
            </span>
            <label className="sr-only" htmlFor="end_date">
              End date
            </label>
            <input id="end_date" type="date" value={draft.end_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} />
          </span>
          <button className="filter-launcher" type="button" aria-haspopup="dialog" onClick={() => setSheetOpen(true)}>
            <Icon icon={faSlidersH} /> Filters
            {pills.length ? <span className="filter-count">{pills.length}</span> : null}
          </button>
          <button type="submit" className="btn btn--primary">
            Apply
          </button>
        </div>

        {pills.length ? (
          <p className="filter-summary">
            {pills.map((pill) => (
              <span key={pill.label} className="filter-pill" title={pill.title}>
                {pill.label} <b>{pill.value}</b>
              </span>
            ))}
            <button
              className="btn btn--quiet"
              type="button"
              onClick={() => {
                setParams(new URLSearchParams());
              }}
            >
              Clear
            </button>
          </p>
        ) : null}

        <div className="chart-bar">
          <div className="field">
            <label className="sr-only" htmlFor="chart_type">
              Chart
            </label>
            <select id="chart_type" name="chart_type" value={kind} onChange={(e) => pickKind(e.target.value)}>
              {CHART_GROUPS.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.kinds.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn-icon"
            id="refresh-chart"
            title="Re-fetch this chart's data, picking up anything tracked since the page loaded"
            onClick={() => void queryClient.invalidateQueries({ queryKey: ["reports", "charts"] })}
          >
            <Icon icon={faSyncAlt} spin={chart.isFetching} />
            <span className="sr-only">Refresh</span>
          </button>
          <label className="check-row chart-compare-toggle" title={!range ? "Pick a start and end date to compare" : NO_COMPARE[kind]}>
            <input type="checkbox" checked={applied.compare && !!compare} disabled={!range || !compare} onChange={(e) => toggleCompare(e.target.checked)} />
            Compare to previous period
            {compare ? null : <span className="muted">(not for this chart)</span>}
          </label>
        </div>
      </form>

      <Sheet className="filter-sheet" open={sheetOpen} onClose={() => setSheetOpen(false)} title="Filter chart data">
        <div className="fields">
          <div className="field">
            <label htmlFor="content-search">Search projects, subprojects, and session notes</label>
            <input
              id="content-search"
              type="search"
              placeholder="Projects, subprojects, or notes"
              value={draft.search}
              onChange={(e) => setDraft({ ...draft, search: e.target.value })}
            />
          </div>

          {semantic ? (
            <div className="check-row">
              <input id="related-search" type="checkbox" checked={draft.related} onChange={(e) => setDraft({ ...draft, related: e.target.checked })} />
              <label htmlFor="related-search">Include related sessions</label>
            </div>
          ) : null}
          {semantic && draft.related ? (
            <SimilaritySlider
              value={draft.similarity ?? accountSimilarity()}
              defaultValue={accountSimilarity()}
              scale={similarityScale()}
              immediate
              onCommit={(value) =>
                setDraft((current) => ({ ...current, similarity: sameCutoff(value, accountSimilarity()) ? null : value }))
              }
            />
          ) : null}

          <div className="field">
            <label htmlFor="project-search">Project name (show subproject breakdown)</label>
            <input
              id="project-search"
              type="text"
              placeholder="Projects"
              autoComplete="off"
              list="project-names"
              value={draft.project_name}
              onChange={(e) => setDraft({ ...draft, project_name: e.target.value })}
            />
            <datalist id="project-names">
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.name} />
              ))}
            </datalist>
          </div>

          <div className="field">
            <label htmlFor="context-filter">Context</label>
            <select id="context-filter" value={draft.context} onChange={(e) => setDraft({ ...draft, context: e.target.value })}>
              <option value="">Active context (header)</option>
              <option value="all">All contexts</option>
              {(contexts.data ?? []).map((ctx) => (
                <option key={ctx.id} value={ctx.id}>
                  {ctx.name}
                </option>
              ))}
            </select>
          </div>

          {tags.data?.length ? (
            <OptionPicker
              label="Tags"
              options={tags.data.map((t) => ({ id: t.id, label: t.name, color: t.color }))}
              selected={draft.tags}
              onChange={(ids) => setDraft({ ...draft, tags: ids })}
              emptyText="No tags match that search."
            />
          ) : null}

          {projects.data?.length ? (
            <OptionPicker
              label="Projects"
              options={projectOptions}
              selected={draft.projects}
              onChange={(ids) => setDraft({ ...draft, projects: ids })}
              searchPlaceholder="Search projects..."
              emptyText="No projects match that search."
              mode={draft.projectMode}
              onModeChange={(mode) => setDraft({ ...draft, projectMode: mode })}
            />
          ) : null}

          <div className="sheet-foot">
            <button
              className="btn btn--ghost"
              type="button"
              onClick={() => {
                setSheetOpen(false);
                setParams(new URLSearchParams());
              }}
            >
              Clear all
            </button>
            <button className="btn btn--primary" type="button" onClick={() => apply(draft)}>
              Apply filters
            </button>
          </div>
        </div>
      </Sheet>

      <section className="slab slab-pad" id="chart_section">
        {loading ? (
          <div id="chart-loading" className="loading-overlay" role="status" aria-live="polite" aria-busy="true">
            <div className="loading-card">
              <span className="loading-leaf" aria-hidden="true">
                {bootstrap().static.leaf ? <img src={bootstrap().static.leaf} alt="" /> : null}
              </span>
              <div className="loading-text">Loading chart…</div>
            </div>
          </div>
        ) : null}

        {before && !empty && !waitingOffline && !chart.isError ? (
          <CompareSummary
            now={totals.data ? totalHours(totals.data.data) : null}
            previous={previousTotals.data ? totalHours(previousTotals.data.data) : null}
            previousRange={before}
            note={compare?.key}
          />
        ) : null}

        {chart.isError ? <ErrorState error={chart.error} onRetry={() => void chart.refetch()} /> : null}

        {waitingOffline ? (
          <p className="empty" role="status">
            You're offline, and this chart hasn't been saved on this device yet. It will load when you're back online.
          </p>
        ) : null}

        {empty ? (
          <p id="chart-empty" className="empty">
            Nothing to chart for these filters. Widen the range, or <AppLink href={urls.sessions()}>check what you have tracked</AppLink>.
          </p>
        ) : null}

        {!chart.isError && !empty && panels && panels.length > 1 ? (
          <div id="canvas_container" className={`chart-panels chart-panels--${kind}${kind === "calendar" && range && periodDays(range) > 140 ? " chart-panels--stack" : ""}`}>
            {panels.map(({ built: panel, label }) => (
              <figure key={label} className="chart-panel">
                <figcaption>{label}</figcaption>
                <div className="chart-panel-box">
                  {panel ? <ChartCanvas built={panel} label={label} /> : <p className="empty">Nothing tracked.</p>}
                </div>
              </figure>
            ))}
          </div>
        ) : !chart.isError && !empty ? (
          <div id="canvas_container" className={CIRCULAR_KINDS.includes(kind) ? "chart-circular" : kind === "calendar" ? "chart-calendar" : undefined}>
            {built ? <ChartCanvas key={built.type} built={built} /> : null}
          </div>
        ) : null}
      </section>
    </>
  );
}
