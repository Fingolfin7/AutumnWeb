import type { components } from "@/api/schema";

type S = components["schemas"];
export type Account = S["Account"];
export type AccountPatch = S["PatchedAccountPatch"];
export type Prefs = S["PreferencesResponse"];
export type PrefsPatch = S["PatchedPreferencesRequest"];
export type FilterUnit = S["FilterUnitEnum"];
export type LunaEffort = S["LunaEffortEnum"];
export type Background = S["Background"];
export type OpenaiSource = Prefs["openai_source"];
export type BackgroundChoice = "bing" | "nasa" | "";

export const FILTER_UNITS: { value: FilterUnit; label: string }[] = [
  { value: "days", label: "Days" },
  { value: "weeks", label: "Weeks" },
  { value: "months", label: "Months" },
  { value: "years", label: "Years" },
  { value: "month_to_date", label: "Month to date" },
  { value: "quarter_to_date", label: "Quarter to date" },
  { value: "year_to_date", label: "Year to date" },
];

export const LUNA_EFFORTS: { value: LunaEffort; label: string }[] = [
  { value: "low", label: "Low effort" },
  { value: "medium", label: "Medium effort" },
  { value: "high", label: "High effort" },
  { value: "xhigh", label: "xHigh effort" },
  { value: "max", label: "Max effort" },
];

export const DIM_MAX = 85;

export interface AccountDraft {
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

/* Number inputs are kept as text while typing; an empty one means "leave as is"
   (the old form preserved the stored value for blank numbers). */
export interface PrefsDraft {
  timezone: string;
  automatic: boolean;
  choice: BackgroundChoice;
  dimming: number;
  filterValue: string;
  filterUnit: FilterUnit;
  insightsValue: string;
  insightsUnit: FilterUnit;
  chartCount: string;
  luna: LunaEffort;
  /** The Related slider's starting cutoff (the server default when unset). */
  similarity: number;
}

export function accountDraft(account: Account): AccountDraft {
  return {
    username: account.username,
    email: account.email,
    first_name: account.first_name,
    last_name: account.last_name,
  };
}

export function choiceOf(prefs: Pick<Prefs, "bing_background" | "nasa_apod_background">): BackgroundChoice {
  return prefs.bing_background ? "bing" : prefs.nasa_apod_background ? "nasa" : "";
}

export function prefsDraft(prefs: Prefs): PrefsDraft {
  return {
    timezone: prefs.timezone,
    automatic: prefs.automatic_background,
    choice: choiceOf(prefs),
    dimming: clampDimming(prefs.background_dimming),
    filterValue: String(prefs.default_filter_value),
    filterUnit: prefs.default_filter_unit as FilterUnit,
    insightsValue: String(prefs.insights_default_filter_value),
    insightsUnit: prefs.insights_default_filter_unit as FilterUnit,
    chartCount: String(prefs.default_chart_project_count),
    luna: prefs.luna_recommendation_effort as LunaEffort,
    similarity: prefs.related_similarity ?? prefs.related_similarity_default,
  };
}

export function clampDimming(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(DIM_MAX, Math.max(0, Math.round(value)));
}

export function isToDate(unit: string): boolean {
  return unit.endsWith("_to_date");
}

/* Only the fields that differ, so a save never rewrites what you did not touch. */
export function accountChanges(draft: AccountDraft, server: Account): AccountPatch | null {
  const patch: AccountPatch = {};
  const username = draft.username.trim();
  if (username !== server.username) patch.username = username;
  const email = draft.email.trim();
  if (email !== server.email) patch.email = email;
  const first = draft.first_name.trim();
  if (first !== server.first_name) patch.first_name = first;
  const last = draft.last_name.trim();
  if (last !== server.last_name) patch.last_name = last;
  return Object.keys(patch).length ? patch : null;
}

function intIn(text: string, min: number, max: number): number | null | "bad" {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return "bad";
  const value = Number(trimmed);
  return value < min || value > max ? "bad" : value;
}

/* Client-side range checks, matching the server's, so a typo is caught before
   anything is uploaded. Keys are the API field names. */
export function validatePrefs(draft: PrefsDraft): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!isToDate(draft.filterUnit) && intIn(draft.filterValue, 1, 1000) === "bad") {
    errors.default_filter_value = "Enter a whole number from 1 to 1000.";
  }
  if (!isToDate(draft.insightsUnit) && intIn(draft.insightsValue, 1, 1000) === "bad") {
    errors.insights_default_filter_value = "Enter a whole number from 1 to 1000.";
  }
  if (intIn(draft.chartCount, 1, 100) === "bad") {
    errors.default_chart_project_count = "Enter a whole number from 1 to 100.";
  }
  if (draft.timezone.length > 64) errors.timezone = "Use at most 64 characters.";
  return errors;
}

export function prefsChanges(draft: PrefsDraft, server: Prefs): PrefsPatch | null {
  const patch: PrefsPatch = {};
  const tz = draft.timezone.trim();
  if (tz && tz !== server.timezone) patch.timezone = tz;

  if (draft.automatic) {
    if (!server.automatic_background) patch.automatic_background = true;
    const bing = draft.choice === "bing";
    const nasa = draft.choice === "nasa";
    if (bing !== server.bing_background) patch.bing_background = bing;
    if (nasa !== server.nasa_apod_background) patch.nasa_apod_background = nasa;
  } else if (server.automatic_background) {
    patch.automatic_background = false;
  }

  if (draft.dimming !== server.background_dimming) patch.background_dimming = draft.dimming;

  const value = intIn(draft.filterValue, 1, 1000);
  if (typeof value === "number" && !isToDate(draft.filterUnit) && value !== server.default_filter_value) {
    patch.default_filter_value = value;
  }
  if (draft.filterUnit !== server.default_filter_unit) patch.default_filter_unit = draft.filterUnit;

  const insights = intIn(draft.insightsValue, 1, 1000);
  if (
    typeof insights === "number" &&
    !isToDate(draft.insightsUnit) &&
    insights !== server.insights_default_filter_value
  ) {
    patch.insights_default_filter_value = insights;
  }
  if (draft.insightsUnit !== server.insights_default_filter_unit)
    patch.insights_default_filter_unit = draft.insightsUnit;

  const count = intIn(draft.chartCount, 1, 100);
  if (typeof count === "number" && count !== server.default_chart_project_count) {
    patch.default_chart_project_count = count;
  }
  if (server.ai_features_enabled && draft.luna !== server.luna_recommendation_effort) {
    patch.luna_recommendation_effort = draft.luna;
  }
  // Stored as null at the server default, so a later change of that default applies.
  const similarity =
    draft.similarity.toFixed(2) === server.related_similarity_default.toFixed(2)
      ? null
      : Number(draft.similarity.toFixed(2));
  if (similarity !== server.related_similarity) patch.related_similarity = similarity;
  return Object.keys(patch).length ? patch : null;
}

/* The default avatar is the shared placeholder; there is nothing to remove. */
export function hasCustomAvatar(url: string): boolean {
  return !!url && !/\/default\.jpg(\?|$)/.test(url);
}

export function timeZoneNames(): string[] {
  const intl = Intl as unknown as {
    supportedValuesOf?: (key: string) => string[];
  };
  try {
    return intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

/* Which API-key text boxes have something to send, and which are being cleared.
   A cleared key wins over a newly typed one, as in the old form. */
export type KeyProvider = "gemini" | "openai" | "claude";
export const KEY_PROVIDERS: KeyProvider[] = ["gemini", "openai", "claude"];

export interface KeyDraft {
  value: string;
  clear: boolean;
}

export function keyActions(
  drafts: Record<KeyProvider, KeyDraft>,
): { provider: KeyProvider; action: "set" | "clear"; key?: string }[] {
  const actions: {
    provider: KeyProvider;
    action: "set" | "clear";
    key?: string;
  }[] = [];
  for (const provider of KEY_PROVIDERS) {
    const draft = drafts[provider];
    if (draft.clear) actions.push({ provider, action: "clear" });
    else if (draft.value.trim()) actions.push({ provider, action: "set", key: draft.value.trim() });
  }
  return actions;
}

/* Details of a 400 as {field: [messages]}. */
export function detailsOf(error: unknown): {
  fields: Record<string, string[]>;
  general: string;
} {
  const fields: Record<string, string[]> = {};
  let general = "";
  const e = error as { details?: unknown; message?: string } | null;
  const details = e?.details;
  if (details && typeof details === "object") {
    for (const [field, value] of Object.entries(details as Record<string, unknown>)) {
      fields[field] = Array.isArray(value) ? value.map(String) : [String(value)];
    }
  }
  if (!Object.keys(fields).length) general = e?.message ?? "Something went wrong.";
  return { fields, general };
}

/* The picture's credit line, as the old page printed it: the description with
   "(© owner)" appended unless the description already names the owner. */
export function backgroundCredit(background: Pick<Background, "description" | "copyright">): string {
  const description = (background.description ?? "").trim();
  const copyright = (background.copyright ?? "").trim();
  if (!copyright || description.includes(copyright)) return description;
  return description ? `${description} (© ${copyright})` : `© ${copyright}`;
}

/* Label of the link to the picture's page; videos (NASA) get "Watch video". */
export function backgroundLinkLabel(background: Pick<Background, "mode" | "video_url">): string {
  if (background.mode === "apod") return background.video_url ? "Watch video at NASA" : "View APOD at NASA";
  return "View at Bing";
}

/* What the OpenAI key slab says about where OpenAI models get their key, from
   the server's openai_source (users/profile.html's have_keys branches).
   `codexConnected` is the live login state, which can be fresher than the
   preferences. */
export function openaiKeyBadge(
  configured: Prefs["configured_api_keys"],
  source: OpenaiSource,
): { label: string; tone: "green" | "red" } {
  if (configured.openai) return { label: "Fallback stored", tone: "green" };
  if (source === "server") return { label: "Server key", tone: "green" };
  return { label: "None", tone: "red" };
}

export type OpenaiNote = "after-codex" | "server-needs-profile" | "server-available" | "paste";

export function openaiKeyNote(
  configured: Prefs["configured_api_keys"],
  source: OpenaiSource,
  codexConnected: boolean,
): OpenaiNote {
  if (codexConnected) return "after-codex";
  if (source === "server") {
    const profileCredentials = configured.gemini || configured.openai || configured.openai_chatgpt || configured.claude;
    return profileCredentials ? "server-available" : "server-needs-profile";
  }
  return "paste";
}
