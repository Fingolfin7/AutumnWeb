import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { AppLink, urls } from "@/app/links";
import { Sheet } from "@/components/Sheet";
import { elapsedSeconds, formatClock } from "@/lib/format";
import { useNow, useTimers } from "./api";

export function TimerDock() {
  const navigate = useNavigate();
  const timers = useTimers();
  const now = useNow();
  const { pathname } = useLocation();
  const [cardVisible, setCardVisible] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const ids = timers.data?.map((timer) => timer.id).join(",");
  useEffect(() => {
    setListOpen(false);
    setCardVisible(false);
    if (pathname !== "/") return;
    const seen = new Map<Element, boolean>();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => seen.set(entry.target, entry.isIntersecting));
      setCardVisible([...seen.values()].some(Boolean));
    }, { rootMargin: "-68px 0px -80px 0px" });
    const attach = () => document.querySelectorAll(".ember-deck article").forEach((card) => {
      if (!seen.has(card)) { seen.set(card, false); observer.observe(card); }
    });
    attach();
    const mutations = new MutationObserver(attach);
    const main = document.getElementById("main-content");
    if (main) mutations.observe(main, { childList: true, subtree: true });
    return () => { observer.disconnect(); mutations.disconnect(); };
  }, [pathname, ids]);
  const timer = timers.data?.[0];
  if (!timer) return null;
  const multiple = timers.data!.length > 1;
  const label = <><span className="live-dot" /><span className="timer-dock-project text-red">{timer.project.name}</span><span className="timer-dock-clock">{formatClock(elapsedSeconds(timer.start, now))}</span>{multiple ? <span>+{timers.data!.length - 1}</span> : null}</>;
  return (
    <><div className={`timer-dock${cardVisible && pathname === "/" ? " timer-dock--card-visible" : ""}`} aria-label="Running timer dock">
      {multiple ? <button type="button" className="timer-dock-open" aria-haspopup="dialog" onClick={() => setListOpen(true)}>{label}</button> :
      <AppLink
        className="timer-dock-open"
        href={urls.home()}
        onClick={() => {
          if (pathname === "/")
            document.getElementById(`timer-${timer.id}`)?.scrollIntoView({ block: "start", behavior: "instant" });
        }}
      >
        {label}
      </AppLink>}
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
    <Sheet open={listOpen} onClose={() => setListOpen(false)} title="Running timers">
      <div className="dock-timer-list">{timers.data!.map((item) => <div key={item.id}>
        <AppLink className="text-red" href={`/#timer-${item.id}`} onClick={() => { setListOpen(false); requestAnimationFrame(() => document.getElementById(`timer-${item.id}`)?.scrollIntoView({ block: "start" })); }}>{item.project.name}</AppLink>
        <span className="timer-dock-clock">{formatClock(elapsedSeconds(item.start, now))}</span>
        <button className="btn btn--stop" type="button" onClick={() => { setListOpen(false); navigate(urls.stopTimer(item.id), { state: { stopRequestedAt: Date.now() } }); }}>Stop</button>
      </div>)}</div>
    </Sheet></>
  );
}
