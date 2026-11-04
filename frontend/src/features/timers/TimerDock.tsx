import { useLocation, useNavigate } from "react-router";
import { AppLink, urls } from "@/app/links";
import { elapsedSeconds, formatClock } from "@/lib/format";
import { useNow, useTimers } from "./api";

export function TimerDock() {
  const navigate = useNavigate();
  const timers = useTimers();
  const now = useNow();
  const { pathname } = useLocation();
  const timer = timers.data?.[0];
  if (!timer) return null;
  return (
    <div className={`timer-dock${pathname === "/" ? " timer-dock--today" : ""}`} aria-label="Running timer dock">
      <AppLink
        className="timer-dock-open"
        href={urls.home()}
        onClick={() => {
          if (pathname === "/")
            document.getElementById(`timer-${timer.id}`)?.scrollIntoView({ block: "start", behavior: "instant" });
        }}
      >
        <span className="live-dot" />
        <span className="timer-dock-project text-red">{timer.project.name}</span>
        <span className="timer-dock-clock">{formatClock(elapsedSeconds(timer.start, now))}</span>
        {timers.data!.length > 1 ? <span>+{timers.data!.length - 1}</span> : null}
      </AppLink>
      <AppLink
        className="btn btn--stop"
        href={urls.stopTimer(timer.id)}
        onClick={(event) => {
          if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          navigate(urls.stopTimer(timer.id), { state: { stopRequestedAt: Date.now() } });
        }}
      >
        Stop
      </AppLink>
    </div>
  );
}
