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
import { formatDayDate, formatDate, formatDuration } from "@/lib/format";
import { groupByDay } from "@/lib/sessions";
import { SessionBand } from "./SessionBand";
import { useSessionList, useSessionTotals, type SessionFilters, type SessionRow } from "./api";
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
    projectMode: include.length || !exclude.length ? "include" : "exclude",
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
  useEffect(() => {
    if (searchText.trim() === applied.search) return;
    const timeout = setTimeout(() => setParams(writeFilters({ ...applied, search: searchText.trim() }), { replace: true }), 300);
    return () => clearTimeout(timeout);
  }, [searchText, applied, setParams]);
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
  const totals = useSessionTotals(apiFilters);
  const relatedQuery = Object.fromEntries(Object.entries(apiFilters).filter(([, value]) => value));
  const summary = useRelatedSummary("sessions", relatedQuery, !!applied.search && semanticSearchAvailable());
  const relatedSummary = summary.data?.available ? summary.data : null;

  const scope = JSON.stringify(apiFilters);
  const [retained, setRetained] = useState<{ scope: string; rows: Record<number, { session: SessionRow; index: number }> }>({ scope, rows: {} });
  useEffect(() => setRetained({ scope, rows: {} }), [scope]);
  const pinned = retained.scope === scope ? retained.rows : {};
  const fetched = list.data?.pages.flatMap((page) => page.sessions) ?? [];
  const all: SessionRow[] = fetched.map((session) => {
    const saved = pinned[session.id]?.session;
    return saved && (saved.version > session.version || (saved.version === session.version && saved.note_html && !session.note_html)) ? saved : session;
  });
  for (const { session, index } of Object.values(pinned).sort((a, b) => a.index - b.index)) {
    if (!all.some((row) => row.id === session.id)) all.splice(Math.min(index, all.length), 0, session);
  }
  const retainNote = (session: SessionRow) => setRetained((previous) => {
    const rows = previous.scope === scope ? previous.rows : {};
    const existing = rows[session.id];
    return { scope, rows: { ...rows, [session.id]: {
      session: { ...session, match: existing?.session.match ?? session.match },
      index: existing?.index ?? Math.max(0, all.findIndex((row) => row.id === session.id)),
    } } };
  });
  const direct = all.filter((s) => s.match !== "related");
  const related = all.filter((s) => s.match === "related");
  const total = list.data?.pages[0]?.total ?? 0;
  const groups = groupByDay(direct);

  const pills = describeFilters(applied, {
    projects: [...(projects.data ?? []), ...all.map((session) => session.project)],
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
      <div className="desk-head journal-title"><h1 className="page-title">Sessions</h1></div>
      {total > 0 || pills.length || applied.search || searchText ? <form className="fields journal-search" onSubmit={onSearch} role="search">
        <div className="searchbar">
          <Icon icon={faSearch} className="muted" />
          <label className="sr-only" htmlFor="content-search">
            Search projects, subprojects, and session notes
          </label>
          <input
            id="content-search"
            type="search"
            placeholder="Search sessions"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          {searchText ? <button className="search-clear btn btn--quiet" type="button" aria-label="Clear search" onClick={() => { setSearchText(""); setParams(writeFilters({ ...applied, search: "" })); }}>Clear</button> : null}
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

        <div className="journal-presets range-tabs" aria-label="Date presets">
          {["This week", "Last week", "30 days"].map((label) => {
            const range = sessionRange(label);
            return <button key={label} type="button" className={`range-tab${applied.start_date === range.start_date && applied.end_date === range.end_date ? " is-active" : ""}`} aria-pressed={applied.start_date === range.start_date && applied.end_date === range.end_date} onClick={() => apply({ ...applied, ...range })}>{label}</button>;
          })}
        </div>
        <p className="filter-summary">
          <span className="result-count">{list.isPending ? "…" : total}</span> session{total === 1 ? "" : "s"}
          {totals.data ? <strong className="journal-filter-total">{formatDuration(totals.data.total_minutes)}</strong> : null}
        </p>
        <div className="journal-filter-chips">
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
        </div>
      </form> : null}

      <Sheet className="filter-sheet" open={sheetOpen} onClose={() => setSheetOpen(false)} title="Filter sessions">
        <div className="fields">
        <div className="journal-presets journal-presets--sheet" aria-label="Date presets">
          {["This week", "Last week", "30 days"].map((label) => {
            const range = sessionRange(label);
            return <button key={label} type="button" className={`range-tab${applied.start_date === range.start_date && applied.end_date === range.end_date ? " is-active" : ""}`} aria-pressed={applied.start_date === range.start_date && applied.end_date === range.end_date} onClick={() => apply({ ...applied, ...range })}>{label}</button>;
          })}
        </div>

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

      {Object.keys(pinned).some((id) => !fetched.some((session) => session.id === Number(id))) ? <p className="muted">Your edited entry stays here until you change the search or filters.</p> : null}
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
                  <SessionBand key={session.id} session={session} day={group.date} search={applied.search} onEditNote={retainNote} onNoteSaved={retainNote} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      ) : !related.length ? (
        <section className="slab">
          {pills.length || applied.search ? (
            <Empty>No sessions match{applied.search ? ` ?${applied.search}?` : " these filters"}. Try another search or clear the filters.</Empty>
          ) : (
            <div className="first-run-empty journal-empty"><span className="ember-seal" aria-hidden="true" /><h2>A little time, a place to keep it.</h2><p>Your sessions and the thoughts that go with them will gather here.</p><AppLink className="btn btn--primary" href={urls.startTimer()}>Start your first timer</AppLink></div>
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
                <SessionBand key={session.id} session={session} search={applied.search} showDate onEditNote={retainNote} onNoteSaved={retainNote} />
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
  if (state.start_date) pills.push({ label: "From", value: formatDate(state.start_date) });
  if (state.end_date) pills.push({ label: "To", value: formatDate(state.end_date) });
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

function sessionRange(label: string) {
  const end = new Date();
  const start = new Date(end);
  if (label === "30 days") start.setDate(start.getDate() - 29);
  else {
    start.setDate(start.getDate() - (start.getDay() + 6) % 7 - (label === "Last week" ? 7 : 0));
    if (label === "Last week") {
      end.setTime(start.getTime());
      end.setDate(start.getDate() + 6);
    }
  }
  const iso = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  return { start_date: iso(start), end_date: iso(end) };
}
