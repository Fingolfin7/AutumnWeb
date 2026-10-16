import type { paths } from "@/api/schema";
import { accountSimilarity, fixed2, parseSimilarity, similarityScale } from "@/features/search/similarity";
import type { ChatFiltersStored, ChatGroup, ChatMessage, InsightOptions, StreamRequest, Usage } from "./types";

/* ---- the session selection (the page's filters) --------------------------- */

/* What the model is given: the sessions these filters select. The Insights
   form's own fields, in the old page's names. */
export interface SelectionFilters {
  search: string;
  related: boolean;
  /** The related cutoff; null = the account's (Profile) default. */
  similarity: number | null;
  project_name: string;
  start_date: string;
  end_date: string;
  note_snippet: string;
  /** "" = the header's active context, "all" = every context, otherwise a context id. */
  context: string;
  tags: number[];
  projects: number[];
  projectMode: "include" | "exclude";
}

export const EMPTY_SELECTION: SelectionFilters = {
  search: "",
  related: false,
  similarity: null,
  project_name: "",
  start_date: "",
  end_date: "",
  note_snippet: "",
  context: "",
  tags: [],
  projects: [],
  projectMode: "exclude",
};

/* "all", a context id, or "" for anything else. */
function contextValue(raw: string | null | undefined): string {
  const value = (raw ?? "").trim().toLowerCase();
  return value === "all" || /^\d+$/.test(value) ? value : "";
}

const TRUTHY = new Set(["1", "true", "on", "yes"]);

function ids(values: unknown): number[] {
  const list = Array.isArray(values) ? values : values === undefined || values === null || values === "" ? [] : [values];
  return list
    .flatMap((value) => String(value).split(","))
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0);
}

/* The old page's GET form: ?search=&related=on&start_date=&tags=1&tags=2&include_projects=... */
export function readSelection(params: URLSearchParams, defaults: { start: string; end: string }): SelectionFilters {
  const include = ids(params.getAll("include_projects"));
  const exclude = ids(params.getAll("exclude_projects"));
  return {
    search: (params.get("search") ?? "").trim(),
    related: TRUTHY.has((params.get("related") ?? "").toLowerCase()),
    similarity: parseSimilarity(params.get("similarity"), similarityScale()),
    project_name: (params.get("project_name") ?? "").trim(),
    start_date: params.get("start_date") || defaults.start,
    end_date: params.get("end_date") || defaults.end,
    note_snippet: (params.get("note_snippet") ?? "").trim(),
    context: contextValue(params.get("context")),
    tags: ids(params.getAll("tags")),
    projects: include.length ? include : exclude,
    projectMode: include.length ? "include" : "exclude",
  };
}

/* The filters a chat was grounded in, as the server stored them. */
export function selectionFromChat(stored: ChatFiltersStored | undefined, defaults: { start: string; end: string }): SelectionFilters {
  const f = (stored ?? {}) as Record<string, unknown>;
  const include = ids(f.include_projects);
  const exclude = ids(f.exclude_projects);
  /* A stored null means the chat was grounded in every context. */
  const context = f.context === null ? "all" : f.context === undefined ? "" : String(f.context);
  return {
    search: typeof f.search === "string" ? f.search : "",
    related: TRUTHY.has(String(f.related ?? "").toLowerCase()),
    similarity: f.similarity == null ? null : parseSimilarity(String(f.similarity), similarityScale()),
    project_name: typeof f.project_name === "string" ? f.project_name : "",
    start_date: typeof f.start_date === "string" && f.start_date ? f.start_date : defaults.start,
    end_date: typeof f.end_date === "string" && f.end_date ? f.end_date : defaults.end,
    note_snippet: typeof f.note_snippet === "string" ? f.note_snippet : "",
    context: contextValue(context),
    tags: ids(f.tags),
    projects: include.length ? include : exclude,
    projectMode: include.length ? "include" : "exclude",
  };
}

/* The filter fields of a stream request. Sent when the chat is new or the user
   re-selected sessions; otherwise the server keeps the chat's stored filters.
   The header's context is sent explicitly (the stream would otherwise fall
   back to whatever the server session remembers). */
export function selectionRequest(
  filters: SelectionFilters,
  defaults: { start: string; end: string },
  activeContextId: number | null,
): Partial<StreamRequest> {
  const body: Partial<StreamRequest> = {};
  if (filters.search) {
    body.search = filters.search;
    if (filters.related) body.related = true;
    if (filters.related && filters.similarity !== null) body.similarity = filters.similarity;
  }
  if (filters.project_name) body.project_name = filters.project_name;
  const start = filters.start_date || defaults.start;
  const end = filters.end_date || defaults.end;
  if (start) body.start_date = start;
  if (end) body.end_date = end;
  if (filters.note_snippet) body.note_snippet = filters.note_snippet;
  const context = filters.context === "all" ? "all" : filters.context ? Number(filters.context) : activeContextId;
  if (context) body.context = context;
  if (filters.tags.length) body.tags = filters.tags;
  if (filters.projects.length) {
    if (filters.projectMode === "include") body.include_projects = filters.projects;
    else body.exclude_projects = filters.projects;
  }
  return body;
}

type Named = { id: number; name: string };

/* Query for GET /api/v2/insights/selection/: the same filter fields the
   stream takes, so the count is of exactly the sessions the model will be
   handed (the server resolves the project name and the active context). */
export type SelectionQuery = NonNullable<paths["/api/v2/insights/selection/"]["get"]["parameters"]["query"]>;

export function selectionQuery(
  filters: SelectionFilters,
  defaults: { start: string; end: string },
  activeContextId: number | null,
): SelectionQuery {
  return selectionRequest(filters, defaults, activeContextId);
}

export interface Pill {
  label: string;
  value: string;
  title?: string;
}

export const RELATED_UNAVAILABLE_TITLE = "Meaning-based matches couldn't be added right now, so only keyword matches are counted.";

/* Summary pills for the applied selection (utils.summarise_search_filters).
   Dates only show when they differ from the profile's default range, so a
   fresh page is not shouting its own defaults. */
export function describeSelection(
  filters: SelectionFilters,
  lookup: { projects: Named[]; tags: Named[]; contexts: Named[] },
  defaults: { start: string; end: string },
  related: { available: boolean; state: "included" | "unavailable" | null },
): Pill[] {
  const names = (list: number[], items: Named[]) => list.map((id) => items.find((item) => item.id === id)?.name ?? `#${id}`).join(", ");
  const pills: Pill[] = [];
  if (filters.search) pills.push({ label: "Search", value: filters.search });
  if (related.available && filters.search && filters.related) {
    pills.push(
      related.state === "unavailable"
        ? { label: "Related", value: "unavailable", title: RELATED_UNAVAILABLE_TITLE }
        : { label: "Including", value: "related" },
    );
    // The cutoff decides which sessions are included, so it is always on show.
    pills.push({ label: "Closeness", value: fixed2(filters.similarity ?? accountSimilarity()) });
  }
  if (filters.project_name) pills.push({ label: "Project", value: filters.project_name });
  if (filters.start_date && filters.start_date !== defaults.start) pills.push({ label: "From", value: filters.start_date });
  if (filters.end_date && filters.end_date !== defaults.end) pills.push({ label: "To", value: filters.end_date });
  if (filters.note_snippet) pills.push({ label: "Note", value: filters.note_snippet });
  if (filters.context) {
    pills.push({ label: "Context", value: filters.context === "all" ? "All contexts" : names([Number(filters.context)], lookup.contexts) });
  }
  if (filters.tags.length) pills.push({ label: "Tags", value: names(filters.tags, lookup.tags) });
  if (filters.projects.length) {
    pills.push({ label: filters.projectMode === "include" ? "Only" : "Excluding", value: names(filters.projects, lookup.projects) });
  }
  return pills;
}

/* ---- provider / model / effort -------------------------------------------- */

export interface ModelSelection {
  provider: string;
  model: string;
  /** "" when the model has no reasoning-effort setting. */
  effort: string;
}

export function effortsFor(options: InsightOptions, provider: string, model: string): string[] {
  return options.providers.find((p) => p.provider === provider)?.models.find((m) => m.value === model)?.reasoning_efforts ?? [];
}

/* Pick the effort a model should open on: keep the wanted one if the model
   offers it, else "high", else the first. */
export function pickEffort(efforts: string[], wanted: string | null | undefined): string {
  if (!efforts.length) return "";
  if (wanted && efforts.includes(wanted)) return wanted;
  return efforts.includes("high") ? "high" : efforts[0]!;
}

const MODEL_REPLACEMENTS: Record<string, Record<string, string>> = {
  openai: {
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5.6-sol": "gpt-6.1-sol",
    "gpt-5.6": "gpt-6.1-sol",
    "gpt-5.6-terra": "gpt-6.1-sol",
    "gpt-6-sol": "gpt-6.1-sol",
  },
  claude: {
    "claude-haiku-4-5": "claude-haiku-5-5",
    "claude-sonnet-5": "claude-sonnet-5-5",
    "claude-opus-5": "claude-opus-5-5",
    "claude-fable-5": "claude-fable-5-1",
  },
};

/* The server's validate_selection: saved models follow their replacement;
   an unknown provider or model falls back to
   the first one the user actually has configured. */
export function resolveSelection(
  options: InsightOptions,
  wanted: { provider?: string | null; model?: string | null; effort?: string | null },
): ModelSelection | null {
  const provider = options.providers.find((p) => p.provider === wanted.provider) ?? options.providers[0];
  if (!provider || !provider.models.length) return null;
  const modelValue = wanted.model ? MODEL_REPLACEMENTS[provider.provider]?.[wanted.model] ?? wanted.model : wanted.model;
  const model = provider.models.find((m) => m.value === modelValue) ?? provider.models[0]!;
  return { provider: provider.provider, model: model.value, effort: pickEffort(model.reasoning_efforts, wanted.effort) };
}

/* A chat stores its model as "provider:model". */
export function splitChatModel(value: string | undefined): { provider: string | null; model: string | null } {
  if (!value) return { provider: null, model: null };
  const at = value.indexOf(":");
  return at === -1 ? { provider: null, model: value } : { provider: value.slice(0, at), model: value.slice(at + 1) };
}

export function effortLabel(effort: string): string {
  if (effort === "xhigh") return "Extra high";
  return effort.charAt(0).toUpperCase() + effort.slice(1);
}

const PROVIDER_LABELS: Record<string, string> = { openai: "OpenAI", gemini: "Gemini", claude: "Claude" };

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/* ---- the chat list -------------------------------------------------------- */

export const CHAT_PAGE_SIZE = 20;

/* The server returns each page of chats already grouped (Today, Yesterday,
   Previous 7 days, Older). Groups that continue onto the next page share a
   label, so merge them back into one list; a chat that moved between pages
   while loading (a new one pushed the rest down) is shown once. */
export function mergeChatPages(pages: { groups: ChatGroup[] }[]): ChatGroup[] {
  const seen = new Set<string>();
  const merged: ChatGroup[] = [];
  for (const page of pages) {
    for (const group of page.groups) {
      const chats = group.chats.filter((chat) => !seen.has(chat.id));
      chats.forEach((chat) => seen.add(chat.id));
      if (!chats.length) continue;
      const last = merged[merged.length - 1];
      if (last && last.label === group.label) last.chats.push(...chats);
      else merged.push({ label: group.label, chats });
    }
  }
  return merged;
}

/* Offset of the next page, or undefined once everything is loaded. */
export function nextChatOffset(pages: { total?: number; offset?: number; groups: ChatGroup[] }[]): number | undefined {
  const last = pages[pages.length - 1];
  if (!last) return undefined;
  const loaded = (last.offset ?? 0) + last.groups.reduce((sum, group) => sum + group.chats.length, 0);
  return last.total !== undefined && loaded < last.total ? loaded : undefined;
}

/* Compact hover stamp (time_formats.chat_hover_stamp): a time for today and
   yesterday, a short date after that, with the year once it is not this year. */
export function chatStamp(value: string, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86_400_000);
  if (days <= 1) {
    return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  }
  const base = `${String(date.getDate()).padStart(2, "0")} ${date.toLocaleDateString("en-GB", { month: "short" })}`;
  return date.getFullYear() === now.getFullYear() ? base : `${base} ${date.getFullYear()}`;
}

/* ---- transcript ----------------------------------------------------------- */

export interface Turn {
  role: "user" | "assistant";
  content: string;
  html: string;
  model: string;
  sources: { link: string; title: string }[];
  error: boolean;
}

/* Only user and assistant messages are on screen; the system context the model
   was primed with is not. */
export function visibleTurns(messages: ChatMessage[], fallbackModel: string): Turn[] {
  return messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content,
      html: m.html,
      model: m.metadata?.model || fallbackModel,
      sources: m.metadata?.sources ?? [],
      error: !!m.metadata?.error,
    }));
}

/* "Copy chat" / "Copy (n)": each message under its sender, divided by rules. */
export function buildTranscript(turns: Pick<Turn, "role" | "content" | "model">[], username: string): string {
  return turns
    .filter((turn) => turn.content.trim())
    .map((turn) => `[${turn.role === "user" ? username : `Autumn (${turn.model})`}]\n${turn.content.trim()}`)
    .join("\n\n---\n\n");
}

export interface UsageTotals {
  prompt: number;
  response: number;
  cached: number;
}

export function sumUsage(usages: (Usage | undefined | null)[]): UsageTotals {
  const total: UsageTotals = { prompt: 0, response: 0, cached: 0 };
  for (const usage of usages) {
    total.prompt += Number(usage?.prompt) || 0;
    total.response += Number(usage?.response) || 0;
    total.cached += Number(usage?.cached) || 0;
  }
  return total;
}

export function formatUsage(total: UsageTotals): string {
  return `In: ${total.prompt.toLocaleString()} · Out: ${total.response.toLocaleString()}${total.cached > 0 ? ` · Cached: ${total.cached.toLocaleString()}` : ""}`;
}

export const USAGE_TITLE =
  "Approximate cumulative token usage for this conversation. In = input/prompt tokens sent to the model, Out = tokens generated by the model (includes reasoning tokens). Cached = the share of In served from the provider's prompt cache, billed at a fraction of the normal rate.";

/* ---- OpenAI connection note ----------------------------------------------- */

export interface ConnectionNote {
  /** Text before the Profile link (the link is shown when `profileLink`). */
  text: string;
  title: string;
  profileLink: boolean;
}

/* The composer's note about where OpenAI models get their key
   (insights.html's openai_connection_source branches). */
export function openaiConnectionNote(source: InsightOptions["openai_source"], hasOpenaiProvider: boolean): ConnectionNote | null {
  switch (source) {
    case "server":
      return {
        text: "OpenAI via server key — add your own in",
        title: "OpenAI models are available through the server OPENAI_API_KEY. Add a personal key in Profile to use your own API account.",
        profileLink: true,
      };
    case "codex_with_api_fallback":
      return {
        text: "OpenAI via Codex login, API key fallback.",
        title: "OpenAI models use your Codex login first. Your OpenAI API key is the fallback if Codex is unavailable or out of usage.",
        profileLink: false,
      };
    case "codex":
      return { text: "OpenAI via Codex login.", title: "OpenAI models are available through your Codex login.", profileLink: false };
    case "profile":
      return { text: "OpenAI via your profile API key.", title: "OpenAI models are using your profile API key.", profileLink: false };
    default:
      return hasOpenaiProvider
        ? null
        : {
            text: "OpenAI needs a key or Codex login — add one in",
            title: "OpenAI models need an API key or Codex login.",
            profileLink: true,
          };
  }
}
