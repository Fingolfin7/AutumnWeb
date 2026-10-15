import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { faSearch, faSlidersH } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { OptionPicker } from "@/components/OptionPicker";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { formatDayDate, formatDuration } from "@/lib/format";
import { groupByDay } from "@/lib/sessions";
import { SessionBand } from "./SessionBand";
import { useSessionList, type SessionFilters, type SessionRow } from "./api";
import { semanticSearchAvailable } from "@/features/charts/api";
import { RelatedSlider } from "@/features/search/RelatedSlider";
import { useRelatedSummary } from "@/features/search/api";
import { fixed2, parseSimilarity, similarityScale } from "@/features/search/similarity";

/* URL <-> filter state. The URL is the source of truth so a filtered view can
   be bookmarked, shared between devices and survives a reload. */
interface FilterState {
  search: string;
  start_date: string;
  end_date: string;
  context: string;
  note_snippet: string;
  tags: number[];
  projects: number[];
  projectMode: "include" | "exclude";
  /** The Related slider's cutoff; null = the account's default. */
  similarity: number | null;
}

function readFilters(params: URLSearchParams): FilterState {
  const ids = (name: string) =>
    params
      .getAll(name)
      .flatMap((value) => value.split(","))
      .map(Number)
      .filter((n) => Number.isInteger(n) && n > 0);
  const include = ids("include_projects");
  const exclude = ids("exclude_projects");
  return {
    search: params.get("search") ?? "",
    start_date: params.get("start_date") ?? "",
    end_date: params.get("end_date") ?? "",
    context: params.get("context") ?? "",
    note_snippet: params.get("note_snippet") ?? "",
    tags: ids("tags"),
    projects: include.length ? include : exclude,
    projectMode: include.length ? "include" : "exclude",
    similarity: parseSimilarity(params.get("similarity"), similarityScale()),
  };
}

function writeFilters(state: FilterState): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of ["search", "start_date", "end_date", "context", "note_snippet"] as const) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.tags.length) params.set("tags", state.tags.join(","));
  if (state.projects.length) params.set(state.projectMode === "include" ? "include_projects" : "exclude_projects", state.projects.join(","));
  if (state.search && state.similarity !== null) params.set("similarity", fixed2(state.similarity));
  return params;
}

export default function SessionsPage() {
  const [params, setParams] = useSearchParams();
  const applied = useMemo(() => readFilters(params), [params]);
  const [draft, setDraft] = useState<FilterState>(applied);
  const [searchText, setSearchText] = useState(applied.search);
  const [sheetOpen, setSheetOpen] = useState(false);
  /* Back/forward changes the URL under us: follow it. */
  useEffect(() => setSearchText(applied.search), [applied.search]);
  const { contextIdsParam } = useActiveContext();
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();

  const apiFilters: SessionFilters = {
    search: applied.search,
    start_date: applied.start_date,
    end_date: applied.end_date,
    note_snippet: applied.note_snippet,
    context_ids: applied.context && applied.context !== "all" ? applied.context : applied.context === "all" ? undefined : contextIdsParam,
    tag_ids: applied.tags.join(","),
    ...(applied.projectMode === "include"
      ? { project_ids: applied.projects.join(",") }
      : { exclude_project_ids: applied.projects.join(",") }),
    ...(applied.search && applied.similarity !== null ? { similarity: applied.similarity } : {}),
  };
  const list = useSessionList(apiFilters);
  const relatedQuery = Object.fromEntries(Object.entries(apiFilters).filter(([, value]) => value));
  const summary = useRelatedSummary("sessions", relatedQuery, !!applied.search && semanticSearchAvailable());
  const relatedSummary = summary.data?.available ? summary.data : null;

  const all: SessionRow[] = list.data?.pages.flatMap((page) => page.sessions) ?? [];
  const direct = all.filter((s) => s.match !== "related");
  const related = all.filter((s) => s.match === "related");
  const total = list.data?.pages[0]?.total ?? 0;
  const groups = groupByDay(direct);

  const pills = describeFilters(applied, {
    projects: projects.data ?? [],
    tags: tags.data ?? [],
    contexts: contexts.data ?? [],
  });

  const apply = (state: FilterState) => {
    setParams(writeFilters(state));
    setSheetOpen(false);
  };

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    apply({ ...applied, search: searchText.trim() });
  };

  return (
    <>
      <h1 className="sr-only">Sessions</h1>
      <form className="fields" onSubmit={onSearch} role="search">
        <div className="searchbar">
          <Icon icon={faSearch} className="muted" />
          <label className="sr-only" htmlFor="content-search">
            Search projects, subprojects, and session notes
          </label>
          <input
            id="content-search"
            type="search"
            placeholder="Projects, subprojects, or notes"
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

        <p className="filter-summary">
          <span className="result-count">{list.isPending ? "…" : total}</span> session{total === 1 ? "" : "s"}
          {pills.map((pill) => (
            <span key={pill.label} className="filter-pill">
              {pill.label} <b>{pill.value}</b>
            </span>
          ))}
          {pills.length || applied.search ? (
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
          ) : null}
        </p>
      </form>

      <Sheet className="filter-sheet" open={sheetOpen} onClose={() => setSheetOpen(false)} title="Filter sessions">
        <div className="fields">
          <div className="two-up">
            <div className="field">
              <label htmlFor="start_date">Start date</label>
              <input id="start_date" type="date" value={draft.start_date} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="end_date">End date</label>
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
          <div className="field">
            <label htmlFor="note_snippet">Note contains</label>
            <input id="note_snippet" type="text" placeholder="Note Snippet" value={draft.note_snippet} onChange={(e) => setDraft({ ...draft, note_snippet: e.target.value })} />
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
              options={projects.data.map((p) => ({ id: p.id, label: p.name }))}
              selected={draft.projects}
              onChange={(ids) => setDraft({ ...draft, projects: ids })}
              searchPlaceholder="Search projects..."
              mode={draft.projectMode}
              onModeChange={(mode) => setDraft({ ...draft, projectMode: mode })}
            />
          ) : null}
          <div className="sheet-foot">
            <button
              className="btn btn--ghost"
              type="button"
              onClick={() => setDraft({ ...readFilters(new URLSearchParams()), search: applied.search })}
            >
              Clear all
            </button>
            <button className="btn btn--primary" type="button" onClick={() => apply({ ...draft, search: applied.search })}>
              Apply filters
            </button>
          </div>
        </div>
      </Sheet>

      {list.isPending ? (
        <section className="slab">
          <Skeleton lines={6} />
        </section>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : groups.length ? (
        <section className="slab session-list" aria-label="Sessions">
          {groups.map((group) => (
            <div className="day-group" key={group.date}>
              <header className="day-head">
                <span className="day-date">{formatDayDate(group.date)}</span>
                <span className="day-total">{formatDuration(group.totalMinutes)}</span>
              </header>
              <ul className="band-list">
                {group.sessions.map((session) => (
                  <SessionBand key={session.id} session={session} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      ) : !related.length ? (
        <section className="slab">
          {pills.length || applied.search ? (
            <Empty>No sessions match these filters.</Empty>
          ) : (
            <Empty>
              No sessions yet. <AppLink href={urls.startTimer()}>Start a timer</AppLink> to begin tracking.
            </Empty>
          )}
        </section>
      ) : null}

      {related.length || relatedSummary ? (
        <section className="slab session-list" aria-label="Related sessions">
          <header className="day-head">
            <span className="day-date">Related</span>
            {relatedSummary ? (
              <span className="day-total">
                {related.length < relatedSummary.count ? `${related.length} of ${relatedSummary.count}` : relatedSummary.count}
              </span>
            ) : null}
          </header>
          {relatedSummary ? (
            <RelatedSlider summary={relatedSummary} loading={list.isFetching && !list.isFetchingNextPage} />
          ) : null}
          {related.length ? (
            <ul className="band-list">
              {related.map((session) => (
                <SessionBand key={session.id} session={session} showDate />
              ))}
            </ul>
          ) : relatedSummary?.count && list.hasNextPage ? (
            /* One ranked list: related matches follow every direct one. */
            <p className="muted slab-pad">They follow the direct matches. Show more below to reach them.</p>
          ) : null}
        </section>
      ) : null}

      {list.hasNextPage ? (
        <div className="slab-foot">
          <button className="btn btn--ghost btn--block" type="button" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
            {list.isFetchingNextPage ? "Loading…" : `Show more (${all.length} of ${total})`}
          </button>
        </div>
      ) : null}
    </>
  );
}

function describeFilters(
  state: FilterState,
  lookup: { projects: { id: number; name: string }[]; tags: { id: number; name: string }[]; contexts: { id: number; name: string }[] },
) {
  const names = (ids: number[], items: { id: number; name: string }[]) =>
    ids.map((id) => items.find((item) => item.id === id)?.name ?? `#${id}`).join(", ");
  const pills: { label: string; value: string }[] = [];
  if (state.start_date) pills.push({ label: "From", value: state.start_date });
  if (state.end_date) pills.push({ label: "To", value: state.end_date });
  if (state.context) {
    pills.push({
      label: "Context",
      value: state.context === "all" ? "All" : lookup.contexts.find((c) => String(c.id) === state.context)?.name ?? state.context,
    });
  }
  if (state.note_snippet) pills.push({ label: "Note", value: state.note_snippet });
  if (state.tags.length) pills.push({ label: "Tags", value: names(state.tags, lookup.tags) });
  if (state.projects.length) {
    pills.push({ label: state.projectMode === "include" ? "Only" : "Excluding", value: names(state.projects, lookup.projects) });
  }
  return pills;
}
