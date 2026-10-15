import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import type { Schedule, ScheduleWrite } from "./scheduleForm";

export type NotificationPreference = components["schemas"]["NotificationPreference"];
export type PreferencePatch = components["schemas"]["PatchedNotificationPreferencePatch"];
export type SnoozeChoice = components["schemas"]["ChoiceEnum"];

const nxKeys = {
  all: ["notifications"] as const,
  preferences: () => ["notifications", "preferences"] as const,
  schedules: () => ["notifications", "schedules"] as const,
};

export function usePreferences() {
  return useQuery({
    queryKey: nxKeys.preferences(),
    queryFn: () => unwrap(api.GET("/api/v2/notifications/preferences/")),
  });
}

export function useSchedules() {
  return useQuery({
    queryKey: nxKeys.schedules(),
    queryFn: () => unwrap(api.GET("/api/v2/notifications/schedules/")),
  });
}

/* The weekly review reads the review time from the preferences, so saving
   them refreshes it too. */
export function useSavePreferences() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PreferencePatch) => unwrap(api.PATCH("/api/v2/notifications/preferences/", { body })),
    onSuccess: (data) => {
      client.setQueryData(nxKeys.preferences(), data);
      void client.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

function useRefreshSchedules() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: nxKeys.schedules() });
}

export function useCreateSchedule() {
  const refresh = useRefreshSchedules();
  return useMutation({
    mutationFn: (body: ScheduleWrite): Promise<Schedule> => unwrap(api.POST("/api/v2/notifications/schedules/", { body })),
    onSuccess: refresh,
    /* A stale form usually means someone changed the list elsewhere. */
    onError: refresh,
  });
}

export function useUpdateSchedule(id: number) {
  const refresh = useRefreshSchedules();
  return useMutation({
    mutationFn: (body: ScheduleWrite): Promise<Schedule> =>
      unwrap(api.PATCH("/api/v2/notifications/schedules/{schedule_id}", { params: { path: { schedule_id: id } }, body })),
    onSuccess: refresh,
    onError: refresh,
  });
}

export function useSnoozeSchedule() {
  const refresh = useRefreshSchedules();
  return useMutation({
    mutationFn: ({ id, choice, version }: { id: number; choice: SnoozeChoice; version: number }): Promise<Schedule> =>
      unwrap(
        api.POST("/api/v2/notifications/schedules/{schedule_id}/snooze/", {
          params: { path: { schedule_id: id } },
          body: { choice, version },
        }),
      ),
    onSuccess: refresh,
    onError: refresh,
  });
}

/* Cancelling names the version it saw, in the body. */
export function useCancelSchedule() {
  const refresh = useRefreshSchedules();
  return useMutation({
    mutationFn: ({ id, version }: { id: number; version: number }) =>
      unwrap(
        api.DELETE("/api/v2/notifications/schedules/{schedule_id}", {
          params: { path: { schedule_id: id } },
          body: { version },
        }),
      ),
    onSuccess: refresh,
    onError: refresh,
  });
}
