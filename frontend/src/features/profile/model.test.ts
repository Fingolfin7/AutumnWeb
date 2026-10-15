import {
  accountChanges,
  accountDraft,
  clampDimming,
  detailsOf,
  hasCustomAvatar,
  keyActions,
  prefsChanges,
  prefsDraft,
  validatePrefs,
  type Account,
  type Prefs,
} from "./model";

const account: Account = { username: "Finrod", email: "f@example.test", first_name: "", last_name: "" };

const prefs = {
  timezone: "Europe/Prague",
  default_filter_value: 1,
  default_filter_unit: "months",
  insights_default_filter_value: 1,
  insights_default_filter_unit: "months",
  default_chart_project_count: 7,
  background_dimming: 48,
  automatic_background: false,
  bing_background: false,
  nasa_apod_background: false,
  luna_recommendation_effort: "xhigh",
  ai_features_enabled: false,
  related_similarity: null,
  related_similarity_default: 0.45,
  related_similarity_min: 0.25,
  related_similarity_max: 0.6,
  active_context_id: null,
  insights_access_enabled: false,
  avatar_url: "/media/default.jpg",
  background: { mode: "none", image_url: null, video_url: null, title: null, description: null, copyright: null, source_url: null },
  configured_api_keys: { gemini: false, openai: false, openai_chatgpt: false, claude: false },
  contexts: [],
  openai_source: null,
} as Prefs;

describe("accountChanges", () => {
  it("is null when nothing changed", () => {
    expect(accountChanges(accountDraft(account), account)).toBeNull();
  });

  it("sends only changed, trimmed fields", () => {
    const draft = { ...accountDraft(account), email: " new@example.test ", first_name: "Fin" };
    expect(accountChanges(draft, account)).toEqual({ email: "new@example.test", first_name: "Fin" });
  });
});

describe("prefsChanges", () => {
  it("is null for an untouched draft", () => {
    expect(prefsChanges(prefsDraft(prefs), prefs)).toBeNull();
  });

  it("sends changed defaults as numbers", () => {
    const draft = { ...prefsDraft(prefs), filterValue: "3", filterUnit: "weeks" as const, chartCount: "10" };
    expect(prefsChanges(draft, prefs)).toEqual({
      default_filter_value: 3,
      default_filter_unit: "weeks",
      default_chart_project_count: 10,
    });
  });

  it("leaves blank numbers and to-date values alone", () => {
    const draft = { ...prefsDraft(prefs), filterValue: "", insightsValue: "9", insightsUnit: "year_to_date" as const };
    expect(prefsChanges(draft, prefs)).toEqual({ insights_default_filter_unit: "year_to_date" });
  });

  it("turns the automatic backdrop on with its source", () => {
    const draft = { ...prefsDraft(prefs), automatic: true, choice: "bing" as const };
    expect(prefsChanges(draft, prefs)).toEqual({ automatic_background: true, bing_background: true });
  });

  it("switches source and clears the other flag", () => {
    const server = { ...prefs, automatic_background: true, bing_background: true } as Prefs;
    const draft = { ...prefsDraft(server), choice: "nasa" as const };
    expect(prefsChanges(draft, server)).toEqual({ bing_background: false, nasa_apod_background: true });
  });

  it("turns automatic off without touching the source flags", () => {
    const server = { ...prefs, automatic_background: true, bing_background: true } as Prefs;
    const draft = { ...prefsDraft(server), automatic: false };
    expect(prefsChanges(draft, server)).toEqual({ automatic_background: false });
  });

  it("only sends the Luna effort for accounts with AI features", () => {
    const draft = { ...prefsDraft(prefs), luna: "low" as const };
    expect(prefsChanges(draft, prefs)).toBeNull();
    const ai = { ...prefs, ai_features_enabled: true } as Prefs;
    expect(prefsChanges({ ...prefsDraft(ai), luna: "low" }, ai)).toEqual({ luna_recommendation_effort: "low" });
  });
});

describe("validatePrefs", () => {
  it("accepts the server's ranges and rejects the rest", () => {
    const ok = prefsDraft(prefs);
    expect(validatePrefs(ok)).toEqual({});
    expect(validatePrefs({ ...ok, filterValue: "0" }).default_filter_value).toBeTruthy();
    expect(validatePrefs({ ...ok, insightsValue: "1001" }).insights_default_filter_value).toBeTruthy();
    expect(validatePrefs({ ...ok, chartCount: "101" }).default_chart_project_count).toBeTruthy();
    expect(validatePrefs({ ...ok, chartCount: "2.5" }).default_chart_project_count).toBeTruthy();
    expect(validatePrefs({ ...ok, filterValue: "" })).toEqual({});
  });

  it("ignores the value of a to-date range", () => {
    expect(validatePrefs({ ...prefsDraft(prefs), filterUnit: "month_to_date", filterValue: "0" })).toEqual({});
  });
});

describe("misc", () => {
  it("clamps dimming to 0-85", () => {
    expect(clampDimming(120)).toBe(85);
    expect(clampDimming(-4)).toBe(0);
    expect(clampDimming(Number.NaN)).toBe(0);
  });

  it("spots the placeholder avatar", () => {
    expect(hasCustomAvatar("/media/default.jpg")).toBe(false);
    expect(hasCustomAvatar("/media/profile_pics/me.png")).toBe(true);
    expect(hasCustomAvatar("")).toBe(false);
  });

  it("plans API key changes, clear winning over typing", () => {
    const drafts = {
      gemini: { value: " abc ", clear: false },
      openai: { value: "typed", clear: true },
      claude: { value: "  ", clear: false },
    };
    expect(keyActions(drafts)).toEqual([
      { provider: "gemini", action: "set", key: "abc" },
      { provider: "openai", action: "clear" },
    ]);
  });

  it("reads validation details", () => {
    expect(detailsOf({ details: { email: ["Enter a valid email address."] } }).fields.email).toEqual([
      "Enter a valid email address.",
    ]);
    expect(detailsOf(new Error("boom")).general).toBe("boom");
  });
});
