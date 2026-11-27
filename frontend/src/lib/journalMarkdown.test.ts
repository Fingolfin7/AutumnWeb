import { expect, it } from "vitest";
import type { SessionRow } from "@/features/sessions/api";
import { sessionListMarkdown, weeklyReviewMarkdown } from "./journalMarkdown";

function session({ id, name, date, note, match }: { id: number; name: string; date: string; note?: string; match?: "direct" | "related" }): SessionRow {
  return {
    id, uuid: null, version: 1,
    project: { id, name },
    subproject_allocations: [],
    start: `${date}T23:00:00Z`, end: `${date}T23:30:00Z`,
    active: false, auto_stop_at: null, notify_on_auto_stop: false,
    duration_minutes: 30, elapsed_minutes: 30, note, match,
  } as SessionRow;
}

it("preserves note markdown and keeps ranked search ordering", () => {
  const note = "**A note**\n\n- item\n  - nested\n\n```js\nconst x = 1;\n```";
  const related = session({ id: 1, name: "Related project", date: "2026-11-10", match: "related" });
  const newest = session({ id: 2, name: "Direct [project]", date: "2026-11-20", note });
  const best = sessionListMarkdown([related, newest], { search: "example", best: true });
  expect(best.indexOf("### Related project")).toBeLessThan(best.indexOf("### Direct"));
  expect(best).toContain("### Direct \\[project\\]");
  expect(best).toContain("> **A note**\n>\n> - item\n>   - nested\n>\n> ```js\n> const x = 1;\n> ```");

  const chronological = sessionListMarkdown([related, newest], { search: "example" });
  expect(chronological).toMatch(/^## \d{4}-\d{2}-\d{2}$/m);
  expect(chronological.indexOf("### Direct")).toBeLessThan(chronological.indexOf("## Related"));
});

it("uses report project order and dates in the profile timezone", () => {
  const first = session({ id: 1, name: "First", date: "2026-11-19", note: "One" });
  const second = session({ id: 2, name: "Second", date: "2026-11-20", note: "Two" });
  const output = weeklyReviewMarkdown({
    week_start: "2026-11-15", week_end: "2026-11-21", timezone: "Africa/Johannesburg",
    per_project: [{ project_id: 1 }, { project_id: 2 }],
  }, [second, first]);

  expect(output.indexOf("## First")).toBeLessThan(output.indexOf("## Second"));
  expect(output).toContain("### Fri 20 Nov, 01:30 · 30m\n\n> One");
  expect(output).toContain("### Sat 21 Nov, 01:30 · 30m\n\n> Two");
});
