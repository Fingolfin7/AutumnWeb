import { splitMinutes } from "@/lib/format";

/* Edit-page sidebar numbers (views/contexts_tags.py _sidebar_project_stats),
   worked out from the project list instead of a server-side aggregate. */
export interface StatsProject {
  status: string;
  total_minutes: number;
  session_count: number;
}

export interface ProjectSummary {
  total: number;
  statusCounts: Record<"active" | "paused" | "complete" | "archived", number>;
  totalMinutes: number;
  averageMinutes: number;
}

export function summarizeProjects(projects: StatsProject[]): ProjectSummary {
  const statusCounts = { active: 0, paused: 0, complete: 0, archived: 0 };
  let totalMinutes = 0;
  let sessions = 0;
  for (const project of projects) {
    if (project.status in statusCounts) statusCounts[project.status as keyof typeof statusCounts] += 1;
    totalMinutes += project.total_minutes;
    sessions += project.session_count;
  }
  return {
    total: projects.length,
    statusCounts,
    totalMinutes,
    averageMinutes: sessions ? totalMinutes / sessions : 0,
  };
}

/** "(2 active, 1 paused)", or "" when every count is zero (`project_status_counts_formatter`). */
export function formatStatusCounts(counts: ProjectSummary["statusCounts"]): string {
  const parts = (["active", "paused", "complete", "archived"] as const)
    .filter((key) => counts[key] > 0)
    .map((key) => `${counts[key]} ${key}`);
  return parts.length ? `(${parts.join(", ")})` : "";
}

/** Every non-zero unit: "1 hour 2 minutes 33 seconds" (`min_formatter`). */
export function formatMinutesFull(minutes: number): string {
  const { days, hours, minutes: m, seconds } = splitMinutes(minutes);
  const unit = (n: number, word: string) => (n > 0 ? [`${n} ${word}${n === 1 ? "" : "s"}`] : []);
  const parts = [...unit(days, "day"), ...unit(hours, "hour"), ...unit(m, "minute"), ...unit(seconds, "second")];
  return parts.length ? parts.join(" ") : "0 seconds";
}

export const NAME_MAX = 100;

/** The context/tag name rules, checked before the request goes out. */
export function validateName(
  raw: string,
  kind: "context" | "tag",
  others: { id: number; name: string }[],
  selfId?: number,
): string | null {
  const name = raw.trim();
  if (!name) return "This field is required.";
  if (name.length > NAME_MAX) return `Ensure this value has at most ${NAME_MAX} characters (it has ${name.length}).`;
  const clash = others.some((other) => other.id !== selfId && other.name.toLowerCase() === name.toLowerCase());
  return clash ? `You already have a ${kind} with this name.` : null;
}
