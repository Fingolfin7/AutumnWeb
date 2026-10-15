import { DEFAULT_KIND, parseKind } from "./build";
import type { ChartKind } from "./payloads";
import { accountSimilarity, fixed2, parseSimilarity, similarityScale } from "@/features/search/similarity";

/* URL <-> filter state for the Charts page. The URL is the source of truth so
   a chart can be bookmarked and survives a reload; the parameter names are the
   old page's (?chart_type=&start_date=&tags=&include_projects=...). */
export interface ChartFilters {
  chart_type: ChartKind;
  start_date: string;
  end_date: string;
  search: string;
  related: boolean;
  /** The related cutoff; null = the account's (Profile) default. */
  similarity: number | null;
  project_name: string;
  /** "" = the header's context, "all", or a context id. */
  context: string;
  tags: number[];
  projects: number[];
  projectMode: "include" | "exclude";
}

export const EMPTY_FILTERS: ChartFilters = {
  chart_type: DEFAULT_KIND,
  start_date: "",
  end_date: "",
  search: "",
  related: false,
  similarity: null,
  project_name: "",
  context: "",
  tags: [],
  projects: [],
  projectMode: "exclude",
};

const TRUTHY = new Set(["1", "true", "on", "yes"]);

export function readFilters(params: URLSearchParams): ChartFilters {
  const ids = (name: string) =>
    params
      .getAll(name)
      .flatMap((value) => value.split(","))
      .map(Number)
      .filter((n) => Number.isInteger(n) && n > 0);
  const include = ids("include_projects");
  const exclude = ids("exclude_projects");
  return {
    chart_type: parseKind(params.get("chart_type")),
    start_date: params.get("start_date") ?? "",
    end_date: params.get("end_date") ?? "",
    search: (params.get("search") ?? "").trim(),
    related: TRUTHY.has((params.get("related") ?? "").toLowerCase()),
    similarity: parseSimilarity(params.get("similarity"), similarityScale()),
    project_name: (params.get("project_name") ?? "").trim(),
    context: params.get("context") ?? "",
    tags: ids("tags"),
    projects: include.length ? include : exclude,
    projectMode: include.length ? "include" : "exclude",
  };
}

export function writeFilters(state: ChartFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (state.chart_type !== DEFAULT_KIND) params.set("chart_type", state.chart_type);
  for (const key of ["start_date", "end_date", "search", "project_name", "context"] as const) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.related && state.search) {
    params.set("related", "on");
    if (state.similarity !== null) params.set("similarity", fixed2(state.similarity));
  }
  for (const tag of state.tags) params.append("tags", String(tag));
  const projectKey = state.projectMode === "include" ? "include_projects" : "exclude_projects";
  for (const project of state.projects) params.append(projectKey, String(project));
  return params;
}

/* ---- API query ---------------------------------------------------------- */

export interface ChartQuery {
  chart_type: ChartKind;
  aggregate?: boolean;
  search?: string;
  related?: boolean;
  similarity?: number;
  project_name?: string;
  start_date?: string;
  end_date?: string;
  context: string;
  tags?: number[];
  include_projects?: number[];
  exclude_projects?: number[];
}

/* `defaults` fills an empty date; `activeContextId` is the header's context
   (null = all), passed explicitly because the endpoint does not guess it. */
export function buildChartQuery(
  filters: ChartFilters,
  defaults: { start?: string; end?: string },
  activeContextId: number | null,
): ChartQuery {
  const query: ChartQuery = {
    chart_type: filters.chart_type,
    context: filters.context || (activeContextId === null ? "all" : String(activeContextId)),
  };
  if (filters.chart_type === "heatmap") query.aggregate = true;
  if (filters.search) {
    query.search = filters.search;
    if (filters.related) query.related = true;
    if (filters.related && filters.similarity !== null) query.similarity = filters.similarity;
  }
  if (filters.project_name) query.project_name = filters.project_name;
  const start = filters.start_date || defaults.start;
  const end = filters.end_date || defaults.end;
  if (start) query.start_date = start;
  if (end) query.end_date = end;
  if (filters.tags.length) query.tags = filters.tags;
  if (filters.projects.length) {
    if (filters.projectMode === "include") query.include_projects = filters.projects;
    else query.exclude_projects = filters.projects;
  }
  return query;
}

/* ---- related pill ------------------------------------------------------- */

/* X-Autumn-Related on a charts response: "included", or "unavailable" when the
   server had to count keyword matches only (no OpenAI key, nothing embedded
   yet, or the provider failing). Missing when related was not requested. */
export type RelatedState = "included" | "unavailable" | null;

export const RELATED_UNAVAILABLE_TITLE = "Meaning-based matches couldn't be added right now, so only keyword matches are counted.";

export function relatedPill(state: RelatedState): { label: string; value: string; title?: string } {
  return state === "unavailable"
    ? { label: "Related", value: "unavailable", title: RELATED_UNAVAILABLE_TITLE }
    : { label: "Including", value: "related" };
}

/* ---- summary pills ------------------------------------------------------ */

export interface Pill {
  label: string;
  value: string;
  title?: string;
}

type Named = { id: number; name: string };

/* The applied narrowing filters echoed back (utils.summarise_search_filters):
   dates only when they are in the URL, ids resolved to names. `related` is the
   state of the chart on screen, shown only for a related search. */
export function describeFilters(
  state: ChartFilters,
  lookup: { projects: Named[]; tags: Named[]; contexts: Named[] },
  related: { available: boolean; state: RelatedState },
): Pill[] {
  const names = (ids: number[], items: Named[]) => ids.map((id) => items.find((item) => item.id === id)?.name ?? `#${id}`).join(", ");
  const pills: Pill[] = [];
  if (state.search) pills.push({ label: "Search", value: state.search });
  if (related.available && state.search && state.related) {
    pills.push(relatedPill(related.state));
    // The cutoff decides the related total, so it is always on show.
    pills.push({ label: "Closeness", value: fixed2(state.similarity ?? accountSimilarity()) });
  }
  if (state.project_name) pills.push({ label: "Project", value: state.project_name });
  if (state.start_date) pills.push({ label: "From", value: state.start_date });
  if (state.end_date) pills.push({ label: "To", value: state.end_date });
  if (state.context) {
    pills.push({
      label: "Context",
      value: state.context === "all" ? "All" : (lookup.contexts.find((c) => String(c.id) === state.context)?.name ?? state.context),
    });
  }
  if (state.tags.length) pills.push({ label: "Tags", value: names(state.tags, lookup.tags) });
  if (state.projects.length) {
    pills.push({ label: state.projectMode === "include" ? "Only" : "Excluding", value: names(state.projects, lookup.projects) });
  }
  return pills;
}
