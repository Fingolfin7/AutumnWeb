import { useId, useMemo, useState } from "react";
import { useAllProjects } from "@/api/meta";
import type { Project } from "@/api/types";
import { rankProjects } from "@/components/ProjectCombobox";
import type { Dashboard } from "@/features/dashboard/api";

type Pick = { project: Project; subprojectIds: number[]; label: string; sublabel: string };

/** Recent project/subproject pairs and project search share one keyboard picker. */
export function CapturePicker({
  value,
  onChange,
  recent,
}: {
  value: Project | null;
  onChange: (project: Project | null, subprojectIds: number[]) => void;
  recent: Dashboard["quick_starts"];
}) {
  const projects = useAllProjects();
  const listId = useId();
  const [text, setText] = useState(value?.name ?? "");
  const [lastValue, setLastValue] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  if (value !== lastValue) {
    setLastValue(value);
    if (value) setText(value.name);
  }
  const picks = useMemo(() => {
    const needle = text.toLowerCase().trim();
    const all = projects.data ?? [];
    const pairs: Pick[] = recent.flatMap((quick) => {
      const project = all.find((p) => p.id === quick.project.id);
      const sublabel = quick.subprojects.map((s) => s.name).join(", ");
      if (!project || (needle && !`${project.name} ${sublabel}`.toLowerCase().includes(needle))) return [];
      return [{ project, subprojectIds: quick.subprojects.map((s) => s.id), label: project.name, sublabel }];
    });
    const names: Pick[] = rankProjects(all, text)
      .filter((p) => !pairs.some((pair) => pair.project.id === p.id && !pair.subprojectIds.length))
      .map((project) => ({ project, subprojectIds: [], label: project.name, sublabel: "" }));
    return [...pairs, ...names].slice(0, 10);
  }, [projects.data, recent, text]);
  const choose = (pick: Pick) => {
    onChange(pick.project, pick.subprojectIds);
    setText(pick.project.name);
    setOpen(false);
    setActive(0);
  };
  return (
    <div
      className="capture-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <input
        id="project-search"
        type="text"
        className="input"
        data-autofocus
        role="combobox"
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={open}
        aria-activedescendant={open && picks[active] ? `${listId}-${active}` : undefined}
        autoComplete="off"
        autoFocus
        placeholder="Search projects or recent subprojects"
        value={text}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onChange={(event) => {
          setText(event.target.value);
          onChange(null, []);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            setActive((index) => Math.max(0, Math.min(picks.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
          } else if (event.key === "Enter" && open && picks[active]) {
            event.preventDefault();
            choose(picks[active]!);
          } else if (event.key === "Escape" && open) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
          }
        }}
      />
      {open ? (
        <ul id={listId} role="listbox" aria-label="Projects and recent subprojects" className="capture-picks">
          {picks.length ? (
            picks.map((pick, index) => (
              <li
                key={`${pick.project.id}-${pick.subprojectIds.join("-")}`}
                role="option"
                id={`${listId}-${index}`}
                aria-selected={active === index}
                aria-label={`${pick.label}${pick.sublabel ? ` / ${pick.sublabel}` : ""}`}
                className={active === index ? "is-active" : ""}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(pick)}
              >
                <span className="text-red">{pick.label}</span>
                {pick.sublabel ? <small className="text-blue">{pick.sublabel}</small> : null}
              </li>
            ))
          ) : (
            <li role="option" aria-disabled="true">
              {projects.isPending
                ? "Loading projects..."
                : projects.isError
                  ? "Projects unavailable. Reconnect to load them."
                  : "No matching projects."}
            </li>
          )}
        </ul>
      ) : null}
    </div>
  );
}
