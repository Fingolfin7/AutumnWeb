import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { describePushError, disablePush, enablePush, permissionState, sendTestPush, type PermissionState } from "@/lib/push";

const COPY: Record<PermissionState, { title: string; detail: string; action?: string }> = {
  loading: { title: "Checking this browser…", detail: "" },
  unavailable: { title: "Notifications are unavailable.", detail: "This browser does not support background notifications." },
  denied: { title: "Notifications are blocked.", detail: "Allow notifications for this site in your browser settings, then try again." },
  granted: { title: "Notifications are on for this browser.", detail: "", action: "Send a test" },
  default: { title: "Notifications are not enabled.", detail: "Needed for reminders while Autumn is in the background.", action: "Enable notifications" },
};

const PUSH_KEY = ["push", "state"] as const;

/* "This browser": enable, test and turn off Web Push here (the .nx-perm block
   and notifications_desk.js). */
export function BrowserPush() {
  const client = useQueryClient();
  const [status, setStatus] = useState("");
  const state = useQuery({ queryKey: PUSH_KEY, queryFn: permissionState, retry: false, refetchOnWindowFocus: true });

  /* Blocking or allowing the site in browser settings changes the answer
     without any request, so follow the permission itself. */
  useEffect(() => {
    let watched: PermissionStatus | undefined;
    const refresh = () => void client.invalidateQueries({ queryKey: PUSH_KEY });
    navigator.permissions
      ?.query({ name: "notifications" })
      .then((result) => {
        watched = result;
        result.addEventListener("change", refresh);
      })
      .catch(() => undefined);
    return () => watched?.removeEventListener("change", refresh);
  }, [client]);

  const act = useMutation({
    mutationFn: async (kind: "enable" | "test" | "off") => {
      if (kind === "test") return sendTestPush();
      if (kind === "off") return disablePush();
      return enablePush();
    },
    onMutate: (kind) => setStatus(kind === "test" ? "Sending a test…" : kind === "off" ? "Turning notifications off…" : "Asking the browser…"),
    onSuccess: (_result, kind) => {
      setStatus(
        kind === "test" ? "Test notification queued." : kind === "off" ? "Notifications are off for this browser." : "Notifications enabled for this browser.",
      );
      void client.invalidateQueries({ queryKey: PUSH_KEY });
    },
    onError: (error, kind) =>
      setStatus(describePushError(error, kind === "off" ? "Notifications could not be turned off." : "Notifications could not be enabled.")),
  });

  const current: PermissionState = state.data?.state ?? "loading";
  const failed = state.isError;
  const copy = failed
    ? { title: "Notification status is unavailable.", detail: "Autumn could not check this browser just now.", action: undefined }
    : COPY[current];
  const devices = state.data?.devices ?? 0;
  const detail = state.data?.detail ?? (current === "granted" && devices > 1 ? `${devices} devices receive notifications.` : copy.detail);

  return (
    <div className="rm-perm nx-perm" data-perm-state={failed ? "unavailable" : current}>
      <div className="rm-perm-row">
        <span className="rm-perm-dot" aria-hidden="true" />
        <p className="rm-perm-text">
          <span className="rm-perm-title">{copy.title}</span>
          <span className="rm-perm-detail">{detail}</span>
        </p>
        {failed ? (
          <button type="button" className="btn btn--quiet rm-perm-action" onClick={() => void state.refetch()}>
            Try again
          </button>
        ) : null}
        {copy.action ? (
          <button
            type="button"
            className="btn btn--quiet rm-perm-action"
            disabled={act.isPending}
            onClick={() => act.mutate(current === "granted" ? "test" : "enable")}
          >
            {copy.action}
          </button>
        ) : null}
        {current === "granted" && !failed ? (
          <button type="button" className="btn btn--ghost rm-perm-unsubscribe" disabled={act.isPending} onClick={() => act.mutate("off")}>
            Turn off
          </button>
        ) : null}
      </div>
      <p className="rm-perm-status" role="status" aria-live="polite">
        {status}
      </p>
    </div>
  );
}
