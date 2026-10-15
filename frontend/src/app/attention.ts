import { focusManager } from "@tanstack/react-query";

/* Polling (running timers every 15 s, the timeline every 5 min) only
   matters while someone is looking. The production database suspends after
   five minutes without queries, so a tab left open and untouched must go
   quiet: after this long without input the app counts as unfocused, which
   pauses every refetchInterval. The next input (or showing the tab again)
   refocuses it, refetching whatever went stale. */
export const IDLE_AFTER_MS = 3 * 60_000;

const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart", "scroll"] as const;

/* pointermove and scroll fire constantly: re-arm the idle timer at most this often. */
const REARM_EVERY_MS = 1_000;

/* Drive TanStack Query's focus from "tab visible and input in the last
   IDLE_AFTER_MS" instead of visibility alone. Returns a cleanup. */
export function watchAttention(idleAfter = IDLE_AFTER_MS): () => void {
  let cleanup = () => {};
  focusManager.setEventListener((setFocused) => {
    let idle = false;
    let lastArmed = 0;
    let timer: number | undefined;
    const visible = () => document.visibilityState !== "hidden";
    const update = () => setFocused(visible() && !idle);
    const arm = () => {
      lastArmed = Date.now();
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        idle = true;
        update();
      }, idleAfter);
    };
    const onActivity = () => {
      if (!idle && Date.now() - lastArmed < REARM_EVERY_MS) return;
      if (idle) {
        idle = false;
        update();
      }
      arm();
    };
    const onVisibility = () => {
      if (visible()) {
        idle = false;
        arm();
      } else {
        window.clearTimeout(timer);
      }
      update();
    };

    arm();
    for (const name of ACTIVITY_EVENTS) window.addEventListener(name, onActivity, { passive: true, capture: true });
    document.addEventListener("visibilitychange", onVisibility);
    cleanup = () => {
      window.clearTimeout(timer);
      for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, onActivity, { capture: true });
      document.removeEventListener("visibilitychange", onVisibility);
    };
    return cleanup;
  });
  return () => cleanup();
}
