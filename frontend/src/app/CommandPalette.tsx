import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import {
  faArrowRight,
  faPlay,
  faSearch,
  faStopwatch,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Dialog } from "@/components/Sheet";
import { rankProjects } from "@/components/ProjectCombobox";
import { useAllProjects } from "@/api/meta";
import { errorMessage } from "@/api/errors";
import { useStartTimer, useTimers } from "@/features/timers/api";
import { bootstrap } from "@/bootstrap";
import { isAppPath, urls } from "./links";
import { useToast } from "./toasts";

interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: IconDefinition;
  run: () => void;
}

/* Ctrl/Cmd-K: start a timer for any project, stop a running one, jump to a
   page, or search sessions, without touching the mouse. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const projects = useAllProjects();
  const timers = useTimers();
  const start = useStartTimer();
  const toast = useToast();
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuery("");
        setActive(0);
        setOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (href: string) => {
    setOpen(false);
    if (isAppPath(href)) navigate(href);
    else window.location.assign(href);
  };

  const commands = useMemo<Command[]>(() => {
    const q = query.trim().toLowerCase();
    const out: Command[] = [];
    for (const timer of (timers.data ?? []).filter((t) => t.id > 0 || t.pending_sync)) {
      if (!q || `stop ${timer.project.name}`.toLowerCase().includes(q)) {
        out.push({
          id: `stop-${timer.id}`,
          group: "Running",
          label: `Stop ${timer.project.name}`,
          icon: faStopwatch,
          run: () => go(urls.stopTimer(timer.id)),
        });
      }
    }
    for (const project of rankProjects(projects.data ?? [], q, q ? 6 : 4)) {
      out.push({
        id: `start-${project.id}`,
        group: "Start a timer",
        label: project.name,
        hint: project.status === "active" ? undefined : project.status,
        icon: faPlay,
        run: () => {
          setOpen(false);
          start.mutate(
            { project_id: project.id, subproject_ids: [], optimistic: { projectName: project.name, subprojects: [] } },
            {
              onSuccess: () => toast.success(`Started ${project.name}.`),
              onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
            },
          );
        },
      });
    }
    const pages: [string, string][] = [
      ["Home", urls.home()],
      ["Timers", urls.timers()],
      ["New timer", urls.startTimer()],
      ["Sessions", urls.sessions()],
      ["Projects", urls.projects()],
      ["Charts", urls.charts()],
      ...(bootstrap().profile.insights_access_enabled ? ([["Insights", urls.insights()]] as [string, string][]) : []),
      ["Weekly review", urls.weeklyReview()],
      ["Notifications", urls.notifications()],
      ["Contexts", urls.contexts()],
      ["Tags", urls.tags()],
      ["New commitment", urls.createCommitment()],
      ["Import", urls.import()],
      ["Export", urls.export()],
      ["Profile", urls.profile()],
    ];
    for (const [label, href] of pages) {
      if (!q || label.toLowerCase().includes(q)) {
        out.push({ id: `page-${href}`, group: "Go to", label, icon: faArrowRight, run: () => go(href) });
      }
    }
    if (q) {
      out.push({
        id: "search",
        group: "Search",
        label: `Search sessions for “${query.trim()}”`,
        icon: faSearch,
        run: () => go(`${urls.sessions()}?search=${encodeURIComponent(query.trim())}`),
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, projects.data, timers.data]);

  useEffect(() => {
    list.current?.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
  }, [active]);

  let lastGroup = "";
  return (
    <Dialog open={open} onClose={() => setOpen(false)} title="Go anywhere">
      <input
        className="palette-input"
        data-autofocus
        placeholder="Start a timer, open a page, search sessions…"
        aria-label="Command"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((i) => Math.min(i + 1, commands.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (event.key === "Enter") {
            event.preventDefault();
            commands[active]?.run();
          }
        }}
      />
      <ul className="palette-list" ref={list} role="listbox">
        {commands.map((command, index) => {
          const header = command.group !== lastGroup ? command.group : null;
          lastGroup = command.group;
          return (
            <li key={command.id} role="option" aria-selected={index === active}>
              {header ? <div className="palette-group">{header}</div> : null}
              <button
                type="button"
                className={`palette-item${index === active ? " is-active" : ""}`}
                onMouseEnter={() => setActive(index)}
                onClick={() => command.run()}
              >
                <Icon icon={command.icon} className="palette-icon" />
                <span>{command.label}</span>
                {command.hint ? <span className="palette-hint">{command.hint}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}
