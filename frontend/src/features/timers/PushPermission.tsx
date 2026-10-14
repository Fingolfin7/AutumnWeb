import { useCallback, useEffect, useState } from "react";
import {
  describePushError,
  disablePush,
  enablePush,
  permissionState,
  sendTestPush,
  type PermissionState,
} from "@/lib/push";

const COPY: Record<PermissionState, { title: string; detail: string; action?: string }> = {
  loading: { title: "Checking notifications…", detail: "" },
  unavailable: { title: "Notifications are unavailable.", detail: "This browser does not support background notifications." },
  denied: { title: "Notifications are blocked.", detail: "Allow notifications for this site in your browser settings, then try again." },
  granted: { title: "Notifications are on for this browser.", detail: "", action: "Send a test" },
  default: { title: "Notifications are not enabled.", detail: "Needed for reminders while Autumn is in the background.", action: "Enable notifications" },
};

/* The notification-permission strip (.rm-perm) under the reminder settings. */
export function PushPermission() {
  const [state, setState] = useState<PermissionState>("loading");
  const [detail, setDetail] = useState<string | undefined>();
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    permissionState()
      .then((result) => {
        setState(result.state);
        setDetail(result.detail);
      })
      .catch(() => setStatus("Notification status is temporarily unavailable."));
  }, []);

  useEffect(refresh, [refresh]);

  const copy = COPY[state];
  const act = async () => {
    setBusy(true);
    try {
      if (state === "granted") {
        setStatus("Sending a test...");
        const result = await sendTestPush();
        setStatus(result.queued ? "Test notification queued." : `${result.sent ?? 0} test notification sent.`);
      } else {
        setStatus("Asking the browser...");
        await enablePush();
        setStatus("Notifications enabled for this browser.");
      }
      refresh();
    } catch (error) {
      setStatus(describePushError(error, "Notifications could not be enabled."));
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async () => {
    setBusy(true);
    setStatus("Turning notifications off...");
    try {
      await disablePush();
      setStatus("Notifications are off for this browser.");
      refresh();
    } catch (error) {
      setStatus(describePushError(error, "Notifications could not be turned off."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rm-perm" data-perm-state={state}>
      <div className="rm-perm-row">
        <span className="rm-perm-dot" aria-hidden="true" />
        <p className="rm-perm-text">
          <span className="rm-perm-title">{copy.title}</span>{" "}
          <span className="rm-perm-detail">{detail ?? copy.detail}</span>
        </p>
        {copy.action ? (
          <button type="button" className="btn btn--quiet rm-perm-action" onClick={act} disabled={busy}>
            {copy.action}
          </button>
        ) : null}
        {state === "granted" ? (
          <button type="button" className="btn btn--ghost rm-perm-unsubscribe" onClick={turnOff} disabled={busy}>
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
