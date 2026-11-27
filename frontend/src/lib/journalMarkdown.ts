import { formatInstant } from "@/features/notifications/dates";
import type { SessionRow } from "@/features/sessions/api";
import { formatJournalDuration, formatTimeRange, localDateKey, parseInstant } from "./format";
import { groupByDay } from "./sessions";

// The generated labels are literal text. The note itself is Markdown, and
// quoting it keeps headings, lists and code inside their session's entry.
const label = (value: string) => value.replace(/\s+/g, " ").replace(/[\\`*_{}\[\]<>#&~]/g, "\\$&").trim();
const dated = (session: SessionRow) => {
  const instant = parseInstant(session.end ?? session.start);
  return instant ? localDateKey(instant) : "";
};
const count = (size: number) => `${size} session${size === 1 ? "" : "s"}`;

function entry(session: SessionRow, context: string[]): string {
  const subprojects = session.subproject_allocations.map((subproject) => label(subproject.name)).join(", ");
  const details = [...context, formatJournalDuration(session.duration_minutes), subprojects, session.pending_sync ? "Saved offline" : ""];
  const heading = `### ${details.filter(Boolean).join(" · ")}`;
  if (!session.note?.trim()) return heading;
  const quote = session.note.split(/\r?\n/).map((line) => (line ? `> ${line}` : ">")).join("\n");
  return `${heading}\n\n${quote}`;
}

export function sessionListMarkdown(sessions: SessionRow[], { search = "", best = false }: { search?: string; best?: boolean } = {}): string {
  const lines = ["# Sessions", `${count(sessions.length)}${search ? ` matching “${label(search)}”` : ""}`];
  const row = (session: SessionRow, showDate: boolean) => entry(session, [
    label(session.project.name),
    showDate ? dated(session) : "",
    formatTimeRange(session.start, session.end),
    best && session.match === "related" ? "Related" : "",
  ]);

  if (best) {
    lines.push("## Best match", ...sessions.map((session) => row(session, true)));
  } else {
    const direct = sessions.filter((session) => session.match !== "related");
    const related = sessions.filter((session) => session.match === "related");
    for (const day of groupByDay(direct)) {
      lines.push(`## ${day.date}`, ...day.sessions.map((session) => row(session, false)));
    }
    if (related.length) lines.push("## Related", ...related.map((session) => row(session, true)));
  }
  return lines.join("\n\n") + "\n";
}

interface WeekSummary {
  week_start: string;
  week_end: string;
  timezone: string;
  per_project: { project_id: number }[];
}

export function sessionsByProject(sessions: SessionRow[]) {
  const projects = new Map<number, SessionRow[]>();
  for (const session of sessions) {
    const group = projects.get(session.project.id);
    if (group) group.push(session);
    else projects.set(session.project.id, [session]);
  }
  return projects;
}

export function weeklyReviewMarkdown(week: WeekSummary, sessions: SessionRow[]): string {
  const lines = [`# Weekly review · ${week.week_start} to ${week.week_end}`, count(sessions.length)];
  const projects = sessionsByProject(sessions);
  const order = new Set([...week.per_project.map((project) => project.project_id), ...projects.keys()]);
  for (const project of order) {
    const group = projects.get(project);
    const first = group?.[0];
    if (!group || !first) continue;
    const total = group.reduce((sum, session) => sum + (session.duration_minutes ?? 0), 0);
    lines.push(
      `## ${label(first.project.name)}`,
      `${count(group.length)} · ${formatJournalDuration(total)}`,
      ...group.map((session) => entry(session, [formatInstant(session.end, week.timezone)])),
    );
  }
  return lines.join("\n\n") + "\n";
}
