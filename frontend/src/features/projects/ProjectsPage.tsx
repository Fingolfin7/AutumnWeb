import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import {
  faCodeBranch,
  faFolderOpen,
  faLayerGroup,
  faPlus,
  faSearch,
  faSlidersH,
  faTags,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { Disclose } from "@/components/Disclose";
import { OptionPicker } from "@/components/OptionPicker";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import type { Commitment } from "@/api/types";
import { useTimers } from "@/features/timers/api";
import { ProjectBand } from "./ProjectBand";
import { useCommitments, useProjectLists } from "./api";
import { describeFilters, emptyFilters, groupByStatus, readFilters, serverQuery, writeFilters, type ProjectFilters } from "./logic";
import { semanticSearchAvailable } from "@/features/charts/api";
import { useActiveContext } from "@/app/context";
import { RelatedSlider } from "@/features/search/RelatedSlider";
import { useRelatedSummary } from "@/features/search/api";

export default function ProjectsPage() {
  const [params, setParams] = useSearchParams();
  const applied = useMemo(() => readFilters(params), [params]);
  const [draft, setDraft] = useState<ProjectFilters>(applied);
  const [searchText, setSearchText] = useState(applied.search);
  const [sheetOpen, setSheetOpen] = useState(false);
  /* Back/forward changes the URL under us: follow it. */
  useEffect(() => setSearchText(applied.search), [applied.search]);

  const lists = useProjectLists(applied);
  const { contextIdsParam } = useActiveContext();
  const { ordering: _ordering, ...relatedQuery } = serverQuery(applied, contextIdsParam);
  const summary = useRelatedSummary("projects", relatedQuery, !!applied.search && semanticSearchAvailable());
  const relatedSummary = summary.data?.available ? summary.data : null;
  const allProjects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const commitments = useCommitments();
  const timers = useTimers();

  const runningIds = useMemo(() => new Set((timers.data ?? []).map((timer) => timer.project.id)), [timers.data]);
  const tagColors = useMemo(() => new Map((tags.data ?? []).map((tag) => [tag.id, tag.color] as const)), [tags.data]);
  /* A project's own active commitment drives the meter on its row. */
  const commitmentByProject = useMemo(() => {
    const map = new Map<number, Commitment>();
    for (const commitment of commitments.data ?? []) {
      if (commitment.aggregation_type === "project" && commitment.active) map.set(commitment.target.id, commitment);
    }
    return map;
  }, [commitments.data]);

  const pills = describeFilters(applied, {
    projects: allProjects.data ?? [],
    tags: tags.data ?? [],
    contexts: contexts.data ?? [],
  });
  const filtered = pills.length > 0;

  const apply = (state: ProjectFilters) => {
    setParams(writeFilters(state));
    setSheetOpen(false);
  };

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    apply({ ...applied, search: searchText.trim() });
  };

  const groups = groupByStatus(lists.data?.direct ?? []);
  const related = lists.data?.related ?? [];
  const band = (project: (typeof related)[number]) => (
    <ProjectBand
      key={project.id}
      project={project}
      running={runningIds.has(project.id)}
      commitment={commitmentByProject.get(project.id)}
      tagColors={tagColors}
    />
  );

  return (
    <>
      <h1 className="sr-only">Projects</h1>
      <form className="fields" onSubmit={onSearch} role="search">
        <div className="searchbar">
          <Icon icon={faSearch} className="muted" />
          <label className="sr-only" htmlFor="content-search">
            Search project names, subprojects, and session notes
          </label>
          <input
            id="content-search"
            type="search"
            placeholder="Names, descriptions, or notes"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <button className="btn btn--primary" type="submit">
            Search
          </button>
          <button
            className="filter-launcher"
            type="button"
            aria-haspopup="dialog"
            onClick={() => {
              setDraft(applied);
              setSheetOpen(true);
            }}
          >
            <Icon icon={faSlidersH} /> Filters
            {pills.length ? <span className="filter-count">{pills.length}</span> : null}
          </button>
        </div>

        {pills.length ? (
          <p className="filter-summary">
            {pills.map((pill) => (
              <span key={pill.label} className="filter-pill">
                {pill.label} <b>{pill.value}</b>
              </span>
            ))}
            <button
              className="btn btn--quiet"
              type="button"
              onClick={() => {
                setSearchText("");
                setParams(new URLSearchParams());
              }}
            >
              Clear
            </button>
          </p>
        ) : null}
      </form>

      <Sheet className="filter-sheet" open={sheetOpen} onClose={() => setSheetOpen(false)} title="Filter projects">
        <div className="fields">
          <div className="two-up">
            <div className="field">
              <label htmlFor="start_date">Active since</label>
              <input id="start_date" type="date" value={draft.start_date} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="end_date">Active until</label>
              <input id="end_date" type="date" value={draft.end_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} />
            </div>
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
          {allProjects.data?.length ? (
            <OptionPicker
              label="Projects"
              options={allProjects.data.map((p) => ({ id: p.id, label: p.name }))}
              selected={draft.projects}
              onChange={(ids) => setDraft({ ...draft, projects: ids })}
              searchPlaceholder="Search projects..."
              mode={draft.projectMode}
              onModeChange={(mode) => setDraft({ ...draft, projectMode: mode })}
              emptyText="No projects match that search."
            />
          ) : null}
          <div className="sheet-foot">
            <button className="btn btn--ghost" type="button" onClick={() => setDraft({ ...emptyFilters, search: applied.search })}>
              Clear all
            </button>
            <button className="btn btn--primary" type="button" onClick={() => apply({ ...draft, search: applied.search })}>
              Apply filters
            </button>
          </div>
        </div>
      </Sheet>

      <div className="action-row">
        <AppLink className="btn btn--primary" href={urls.createProject()}>
          <Icon icon={faPlus} /> New project
        </AppLink>
        <AppLink className="btn btn--ghost" href={urls.mergeProjects()}>
          <Icon icon={faCodeBranch} /> Merge
        </AppLink>
        <AppLink className="btn btn--quiet" href={urls.contexts()}>
          <Icon icon={faLayerGroup} /> Contexts
        </AppLink>
        <AppLink className="btn btn--quiet" href={urls.tags()}>
          <Icon icon={faTags} /> Tags
        </AppLink>
      </div>

      {lists.isPending ? (
        <section className="slab">
          <Skeleton lines={6} />
        </section>
      ) : lists.isError ? (
        <ErrorState error={lists.error} onRetry={() => void lists.refetch()} />
      ) : groups.length ? (
        groups.map((group) => (
          <Disclose
            key={group.status}
            id={`projects-${group.status}`}
            icon={faFolderOpen}
            iconClass="text-red"
            title={group.label}
            summary={group.projects.length}
            defaultOpen={group.status === "active"}
          >
            <ul className="band-list band-list--grid">{group.projects.map(band)}</ul>
          </Disclose>
        ))
      ) : (
        <section className="slab">
          {filtered ? (
            <Empty>
              No projects match these filters.{" "}
              <AppLink href={urls.projects()} onClick={() => setSearchText("")}>
                Clear them
              </AppLink>{" "}
              to see everything.
            </Empty>
          ) : (
            <Empty>
              No projects yet. <AppLink href={urls.createProject()}>Create one</AppLink> to start tracking.
            </Empty>
          )}
        </section>
      )}

      {related.length || relatedSummary ? (
        <section className="slab" aria-label="Related projects">
          <header className="day-head">
            <span className="day-date">Related</span>
            <span className="day-total">{related.length}</span>
          </header>
          {relatedSummary ? <RelatedSlider summary={relatedSummary} loading={lists.isFetching} /> : null}
          {related.length ? <ul className="band-list band-list--grid">{related.map(band)}</ul> : null}
        </section>
      ) : null}
    </>
  );
}
