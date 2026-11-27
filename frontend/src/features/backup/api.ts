import { useQuery, type QueryClient } from "@tanstack/react-query";
import { api, redirectToLogin, requestJson, unwrap } from "@/api/client";
import { ApiError, toApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import type { components } from "@/api/schema";
import { BOOTSTRAP_REFRESHED, bootstrap } from "@/bootstrap";
import { announce } from "@/lib/broadcast";
import { localDateKey } from "@/lib/format";
import { filenameFromDisposition, saveBlob } from "@/features/import-export/download";
import { fetchPreferences } from "@/features/profile/api";
import { applyAvatar, applyBackground, applyDimming, applyPrefs, refreshBootstrapProfile, syncHeaderDimming } from "@/features/profile/shell";

/* Account backup: one ZIP of everything in the account (not the CLI-format
   Import/Export). Restore is two steps on the same file: preview says what
   it would add and what conflicts, restore applies that preview (its token)
   and nothing else. */

export type BackupPreview = components["schemas"]["BackupPreview"];
type BackupRestoreResult = components["schemas"]["BackupRestoreResult"];

export const backupKeys = { summary: () => ["backup", "summary"] as const };

export function useBackupSummary() {
  return useQuery({
    queryKey: backupKeys.summary(),
    queryFn: ({ signal }) => unwrap(api.GET("/api/v2/backup/summary/", { signal })),
    staleTime: 0,
  });
}

/* The ZIP, or a JSON error. Fetched (not navigated to) so a failure shows
   here instead of replacing the page. */
export async function downloadBackup({ insights, attachments }: { insights: boolean; attachments: boolean }): Promise<string> {
  const query = new URLSearchParams({
    include_insights: String(insights),
    include_attachments: String(insights && attachments),
  });
  let response: Response;
  try {
    response = await fetch(`/api/v2/backup/?${query}`, {
      credentials: "same-origin",
      headers: { Accept: "application/zip, application/json", "X-Requested-With": "XMLHttpRequest" },
    });
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (response.status === 401) redirectToLogin();
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw toApiError(response.status, body);
  }
  const filename = filenameFromDisposition(response.headers.get("Content-Disposition")) ?? `autumn-backup-${localDateKey(new Date())}.zip`;
  saveBlob(await response.blob(), filename);
  return filename;
}

export function previewBackup(file: File, signal?: AbortSignal): Promise<BackupPreview> {
  const body = new FormData();
  body.append("file", file);
  return requestJson<BackupPreview>("POST", "/api/v2/backup/preview/", body, { signal });
}

export function restoreBackup(file: File, previewToken: string): Promise<BackupRestoreResult> {
  const body = new FormData();
  body.append("file", file);
  body.append("preview_token", previewToken);
  return requestJson<BackupRestoreResult>("POST", "/api/v2/backup/restore/", body);
}

const SECTION_LABELS: Record<string, string> = {
  contexts: "Contexts",
  tags: "Tags",
  projects: "Projects",
  subprojects: "Subprojects",
  sessions: "Sessions",
  commitments: "Commitments",
  commitment_revisions: "Commitment changes",
  commitment_periods: "Commitment periods",
  commitment_adjustments: "Commitment adjustments",
  profile: "Profile settings",
  notification_preferences: "Notification settings",
  reminder_schedules: "Planned reminders",
  insight_chats: "Insights chats",
  insight_messages: "Insights messages",
  insight_attachments: "Insights files",
};

export function sectionLabel(section: string): string {
  const known = SECTION_LABELS[section];
  if (known) return known;
  const words = section.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Sections with anything in them, in the server's order, plus totals. */
export function inventory(counts: BackupPreview["counts"]) {
  const rows = Object.entries(counts)
    .map(([section, count]) => ({ section, label: sectionLabel(section), add: count.add ?? 0, identical: count.identical ?? 0, conflict: count.conflict ?? 0 }))
    .filter((row) => row.add + row.identical + row.conflict > 0);
  const total = rows.reduce((sum, row) => ({ add: sum.add + row.add, identical: sum.identical + row.identical, conflict: sum.conflict + row.conflict }), { add: 0, identical: 0, conflict: 0 });
  return { rows, total };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/* A restore can change anything: every cached query, the other open tabs,
   and the bootstrap blob the shell read at startup (profile, backdrop,
   avatar, contexts and the active context). Best effort: whatever fails
   here is caught up by the next page load. */
export async function refreshAfterRestore(client: QueryClient): Promise<void> {
  announce("timers", "sessions", "projects", "commitments", "meta");
  await client.invalidateQueries();
  try {
    const fresh = await client.fetchQuery({ queryKey: keys.preferences(), queryFn: fetchPreferences, staleTime: 0 });
    applyPrefs(fresh);
    applyBackground(fresh.background);
    applyDimming(fresh.background_dimming);
    syncHeaderDimming(fresh.background_dimming);
    applyAvatar(fresh.avatar_url);
    const blob = bootstrap();
    blob.profile.insights_access_enabled = fresh.insights_access_enabled;
    blob.contexts = fresh.contexts.map(({ id, name }) => ({ id, name }));
    blob.active_context_id = fresh.active_context_id;
    await refreshBootstrapProfile();
  } catch {
    /* the next page load catches up */
  }
  window.dispatchEvent(new Event(BOOTSTRAP_REFRESHED));
}
