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
import { buildChart, CHART_GROUPS, CIRCULAR_KINDS, parseKind } from "./build";
import { buildChartQuery, describeFilters, EMPTY_FILTERS, readFilters, writeFilters, type ChartFilters } from "./filters";

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
  const filtersKey = writeFilters({ ...effective, chart_type: EMPTY_FILTERS.chart_type }).toString();
  useEffect(() => setDraft((current) => ({ ...effective, chart_type: current.chart_type })), [filtersKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const semantic = semanticSearchAvailable();
  const query = useMemo(() => buildChartQuery(applied, defaults, contextId), [applied, defaults, contextId]);
  const chart = useChartData(query, true);
  const kind = applied.chart_type;

  const built = useMemo(
    () => (chart.data ? buildChart(kind, chart.data.data, { projectLimit: bootstrap().profile.default_chart_project_count || 7, subprojects: !!applied.project_name }) : null),
    [chart.data, kind, applied.project_name],
  );

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

  const loading = chart.isPending || chart.isFetching;
  const empty = !loading && !chart.isError && !built;

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

        {chart.isError ? <ErrorState error={chart.error} onRetry={() => void chart.refetch()} /> : null}

        {empty ? (
          <p id="chart-empty" className="empty">
            Nothing to chart for these filters. Widen the range, or <AppLink href={urls.sessions()}>check what you have tracked</AppLink>.
          </p>
        ) : null}

        {!chart.isError && !empty ? (
          <div id="canvas_container" className={CIRCULAR_KINDS.includes(kind) ? "chart-circular" : undefined}>
            {built ? <ChartCanvas key={built.type} built={built} /> : null}
          </div>
        ) : null}
      </section>
    </>
  );
}
