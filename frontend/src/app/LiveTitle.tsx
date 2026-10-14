import { useEffect } from "react";
import { useNow, useTimers } from "@/features/timers/api";
import { elapsedSeconds } from "@/lib/format";
import { setLiveTitle } from "./title";

const pad = (n: number) => String(n).padStart(2, "0");

/* "▶ 1:05:12 Gym · Sessions · Autumn" while a timer runs. With several, the
   most recently started one is shown, plus a count. */
export function LiveTitle() {
  const timers = useTimers();
  const running = (timers.data ?? []).filter((t) => t.id > 0);
  const now = useNow(1000);

  const latest = running.reduce<(typeof running)[number] | null>(
    (best, timer) => (!best || Date.parse(timer.start) > Date.parse(best.start) ? timer : best),
    null,
  );
  let text: string | null = null;
  if (latest) {
    const s = elapsedSeconds(latest.start, now);
    const clock = `${Math.floor(s / 3600)}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
    text = `▶ ${clock} ${latest.project.name}${running.length > 1 ? ` (+${running.length - 1})` : ""}`;
  }

  useEffect(() => setLiveTitle(text), [text]);
  useEffect(() => () => setLiveTitle(null), []);
  return null;
}
