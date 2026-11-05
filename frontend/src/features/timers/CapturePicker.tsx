import { useId, useMemo, useState } from "react";
import { useAllProjects, useSubprojects } from "@/api/meta";
import type { Project } from "@/api/types";
import { rankProjects } from "@/components/ProjectCombobox";
import type { Dashboard } from "@/features/dashboard/api";

export function CapturePickLabel({ project, sublabel }: { project: string; sublabel?: string }) {
  return <span className="capture-pick-label"><span className="text-red">{project}</span>{sublabel ? <small className="text-blue">{sublabel}</small> : null}</span>;
}

type Pick = { project: Project; subprojectIds: number[]; label: string; sublabel: string };

/** Recent project/subproject pairs and project search share one keyboard picker. */
export function CapturePicker({
  value,
  onChange,
  onStart,
  recent,
  id = "project-search",
  autoFocus = true,
  placeholder = "Search projects or recent subprojects",
}: {
  value: Project | null;
  onChange: (project: Project | null, subprojectIds: number[]) => void;
  onStart?: (project: Project, subprojectIds: number[]) => void;
  recent: Dashboard["quick_starts"];
  id?: string;
  autoFocus?: boolean;
  placeholder?: string;
}) {
  const projects = useAllProjects();
  const listId = useId();
  const [text, setText] = useState(value?.name ?? "");
  const [lastValue, setLastValue] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const exactProject = projects.data?.find((project) => project.name.toLowerCase() === text.trim().toLowerCase());
  const searchedSubs = useSubprojects(exactProject?.id);
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
    if (exactProject) pairs.push(...(searchedSubs.data ?? []).map((sub) => ({ project: exactProject, subprojectIds: [sub.id], label: exactProject.name, sublabel: sub.name })));
    const unique = [...new Map(pairs.map((pair) => [`${pair.project.id}:${[...pair.subprojectIds].sort().join(",")}`, pair])).values()];
    const ranked = rankProjects(all, text, 12);
    const ordered = [...new Map([...unique.map((pair) => pair.project), ...ranked].map((project) => [project.id, project])).values()];
    // Each project appears once, followed by its visibly named recent subprojects.
    return ordered.flatMap((project) => [
      { project, subprojectIds: [], label: project.name, sublabel: "" },
      ...unique.filter((pair) => pair.project.id === project.id && pair.subprojectIds.length),
    ]);

  }, [projects.data, recent, text, exactProject, searchedSubs.data]);
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
        id={id}
        type="text"
        className="input"
        data-autofocus={autoFocus || undefined}
        role="combobox"
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={open}
        aria-activedescendant={open && picks[active] ? `${listId}-${active}` : undefined}
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder={placeholder}
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
            const pick = picks[active]!;
            choose(pick);
            onStart?.(pick.project, pick.subprojectIds);
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
                className={`${active === index ? "is-active" : ""}${pick.sublabel ? " capture-pick-sub" : ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(pick)}
              >
                <CapturePickLabel project={pick.label} sublabel={pick.sublabel} />
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
