import {
  buildTranscript,
  chatStamp,
  describeSelection,
  EMPTY_SELECTION,
  formatUsage,
  limitGroups,
  pickEffort,
  previewQuery,
  readSelection,
  resolveSelection,
  selectionFromChat,
  selectionRequest,
  splitChatModel,
  sumUsage,
  visibleTurns,
} from "./logic";
import type { ChatGroup, ChatMessage, InsightOptions } from "./types";

const defaults = { start: "2026-09-14", end: "2026-10-14" };
const dates = { start_date: defaults.start, end_date: defaults.end };

const options: InsightOptions = {
  default_start_date: defaults.start,
  default_end_date: defaults.end,
  providers: [
    {
      provider: "openai",
      models: [
        { value: "gpt-a", label: "GPT A", reasoning_efforts: ["low", "medium", "high"] },
        { value: "gpt-b", label: "GPT B", reasoning_efforts: ["low", "max"] },
      ],
    },
    { provider: "claude", models: [{ value: "claude-x", label: "Claude X", reasoning_efforts: [] }] },
  ],
};

describe("selection <-> request", () => {
  it("reads the old page's query string, defaulting the dates", () => {
    const params = new URLSearchParams("search=oauth&related=on&tags=3&tags=4&include_projects=7&context=2");
    const f = readSelection(params, defaults);
    expect(f).toMatchObject({ search: "oauth", related: true, tags: [3, 4], projects: [7], projectMode: "include", context: "2", start_date: defaults.start });
  });

  it("restores a chat's stored filters, including string ids", () => {
    const f = selectionFromChat({ search: "x", tags: ["5"] as unknown as number[], exclude_projects: [9], context: 3, start_date: "2026-01-01" }, defaults);
    expect(f).toMatchObject({ search: "x", tags: [5], projects: [9], projectMode: "exclude", context: "3", start_date: "2026-01-01", end_date: defaults.end });
  });

  it("sends only what is set, with related only alongside a search, and the header context", () => {
    expect(selectionRequest({ ...EMPTY_SELECTION, related: true }, defaults, null)).toEqual({ start_date: defaults.start, end_date: defaults.end });
    expect(selectionRequest({ ...EMPTY_SELECTION, search: "a", related: true, tags: [1], projects: [2], projectMode: "include" }, defaults, 6)).toEqual({
      search: "a",
      related: true,
      start_date: defaults.start,
      end_date: defaults.end,
      context: 6,
      tags: [1],
      include_projects: [2],
    });
    expect(selectionRequest({ ...EMPTY_SELECTION, context: "4", projects: [2] }, defaults, 6)).toMatchObject({ context: 4, exclude_projects: [2] });
  });
});

describe("previewQuery", () => {
  const projects = [
    { id: 1, name: "Writing" },
    { id: 2, name: "Rewriting notes" },
    { id: 3, name: "Cooking" },
  ];

  it("maps filters onto the sessions list parameters", () => {
    const result = previewQuery({ ...EMPTY_SELECTION, ...dates, search: "a", related: true, tags: [1, 2], projects: [3] }, projects, 5);
    expect(result).toEqual({
      none: false,
      query: { search: "a", related: true, start_date: defaults.start, end_date: defaults.end, context_ids: "5", tag_ids: "1,2", exclude_project_ids: "3" },
    });
  });

  it("turns a project-name match into project ids (case-insensitive contains)", () => {
    expect(previewQuery({ ...EMPTY_SELECTION, project_name: "WRIT" }, projects, null)).toEqual({ none: false, query: { project_ids: "1,2" } });
  });

  it("intersects the name match with an include list, and is empty when nothing can match", () => {
    expect(previewQuery({ ...EMPTY_SELECTION, project_name: "writ", projects: [2, 3], projectMode: "include" }, projects, null)).toEqual({
      none: false,
      query: { project_ids: "2" },
    });
    expect(previewQuery({ ...EMPTY_SELECTION, project_name: "zzz" }, projects, null)).toEqual({ none: true });
    expect(previewQuery({ ...EMPTY_SELECTION, project_name: "cook", projects: [1], projectMode: "include" }, projects, null)).toEqual({ none: true });
  });

  it("uses the chosen context over the header's", () => {
    expect(previewQuery({ ...EMPTY_SELECTION, context: "8" }, projects, 5)).toEqual({ none: false, query: { context_ids: "8" } });
  });
});

describe("describeSelection", () => {
  const lookup = { projects: [{ id: 1, name: "Writing" }], tags: [{ id: 2, name: "deep" }], contexts: [{ id: 3, name: "Work" }] };

  it("shows dates only when they differ from the default range", () => {
    expect(describeSelection({ ...EMPTY_SELECTION, ...dates }, lookup, defaults, { available: true, state: null })).toEqual([]);
    const pills = describeSelection({ ...EMPTY_SELECTION, start_date: "2026-01-01", end_date: defaults.end }, lookup, defaults, { available: true, state: null });
    expect(pills).toEqual([{ label: "From", value: "2026-01-01" }]);
  });

  it("resolves ids to names and flips the related pill when meaning search is unavailable", () => {
    const f = { ...EMPTY_SELECTION, search: "x", related: true, context: "3", tags: [2], projects: [1], projectMode: "include" as const };
    const pills = describeSelection(f, lookup, defaults, { available: true, state: "included" });
    expect(pills.map((p) => `${p.label}=${p.value}`)).toEqual(["Search=x", "Including=related", "Context=Work", "Tags=deep", "Only=Writing"]);
    const unavailable = describeSelection(f, lookup, defaults, { available: true, state: "unavailable" });
    expect(unavailable[1]).toMatchObject({ label: "Related", value: "unavailable" });
    expect(unavailable[1]!.title).toBeTruthy();
    expect(describeSelection(f, lookup, defaults, { available: false, state: null }).some((p) => p.label === "Including")).toBe(false);
  });
});

describe("model selection", () => {
  it("falls back to the first provider and model the user has", () => {
    expect(resolveSelection(options, {})).toEqual({ provider: "openai", model: "gpt-a", effort: "high" });
    expect(resolveSelection(options, { provider: "gemini", model: "nope" })).toEqual({ provider: "openai", model: "gpt-a", effort: "high" });
    expect(resolveSelection(options, { provider: "claude", model: "bad" })).toEqual({ provider: "claude", model: "claude-x", effort: "" });
    expect(resolveSelection({ ...options, providers: [] }, {})).toBeNull();
  });

  it("keeps a valid effort and otherwise prefers high, then the first", () => {
    expect(resolveSelection(options, { provider: "openai", model: "gpt-a", effort: "low" })?.effort).toBe("low");
    expect(pickEffort(["low", "max"], "high")).toBe("low");
    expect(pickEffort(["low", "high"], "xhigh")).toBe("high");
    expect(pickEffort([], "high")).toBe("");
  });

  it("splits a chat's stored provider:model", () => {
    expect(splitChatModel("openai:gpt-a")).toEqual({ provider: "openai", model: "gpt-a" });
    expect(splitChatModel("gpt-a")).toEqual({ provider: null, model: "gpt-a" });
    expect(splitChatModel(undefined)).toEqual({ provider: null, model: null });
  });
});

describe("chat list", () => {
  const group = (label: string, n: number): ChatGroup => ({
    label,
    chats: Array.from({ length: n }, (_, i) => ({ id: `${label}-${i}`, title: `${label} ${i}`, updated_at: "2026-10-14T10:00:00Z" })),
  });

  it("shows the newest chats first up to the limit, across groups", () => {
    const groups = [group("Today", 3), group("Yesterday", 4), group("Older", 5)];
    const view = limitGroups(groups, 5);
    expect(view.groups.map((g) => [g.label, g.chats.length])).toEqual([
      ["Today", 3],
      ["Yesterday", 2],
    ]);
    expect(view).toMatchObject({ total: 12, shown: 5 });
    expect(limitGroups(groups, 20)).toMatchObject({ total: 12, shown: 12 });
  });

  it("stamps today and yesterday with a time, older chats with a date", () => {
    const now = new Date(2026, 9, 14, 15, 0);
    expect(chatStamp(new Date(2026, 9, 14, 14, 14).toISOString(), now)).toMatch(/^2:14\s?PM$/i);
    expect(chatStamp(new Date(2026, 9, 13, 9, 5).toISOString(), now)).toMatch(/^9:05\s?AM$/i);
    expect(chatStamp(new Date(2026, 7, 13, 9, 5).toISOString(), now)).toBe("13 Aug");
    expect(chatStamp(new Date(2025, 7, 13, 9, 5).toISOString(), now)).toBe("13 Aug 2025");
  });
});

describe("transcript", () => {
  const message = (role: ChatMessage["role"], content: string, metadata: ChatMessage["metadata"] = {}): ChatMessage => ({
    role,
    content,
    html: `<p>${content}</p>`,
    created_at: "2026-10-14T10:00:00Z",
    metadata,
  });

  it("hides system messages and fills the model from the chat", () => {
    const turns = visibleTurns(
      [
        message("system", "context"),
        message("user", "How much?"),
        message("assistant", "Lots.", { model: "gpt-a", sources: [{ link: "https://example.com", title: "Doc" }], error: true }),
        message("assistant", "More", {}),
      ],
      "fallback-model",
    );
    expect(turns.map((t) => [t.role, t.model, t.error])).toEqual([
      ["user", "fallback-model", false],
      ["assistant", "gpt-a", true],
      ["assistant", "fallback-model", false],
    ]);
    expect(turns[1]!.sources).toHaveLength(1);
  });

  it("builds the copied transcript with senders and rules, skipping empty messages", () => {
    const text = buildTranscript(
      [
        { role: "user", content: " hello ", model: "" },
        { role: "assistant", content: "hi there", model: "gpt-a" },
        { role: "assistant", content: "  ", model: "gpt-a" },
      ],
      "Finrod",
    );
    expect(text).toBe("[Finrod]\nhello\n\n---\n\n[Autumn (gpt-a)]\nhi there");
  });

  it("sums token usage across messages and formats it", () => {
    const total = sumUsage([{ prompt: 1200, response: 300, cached: 200 }, undefined, { prompt: 800, response: 100 }]);
    expect(total).toEqual({ prompt: 2000, response: 400, cached: 200 });
    expect(formatUsage(total)).toBe(`In: ${(2000).toLocaleString()} · Out: 400 · Cached: 200`);
    expect(formatUsage({ prompt: 0, response: 0, cached: 0 })).toBe("In: 0 · Out: 0");
  });
});
