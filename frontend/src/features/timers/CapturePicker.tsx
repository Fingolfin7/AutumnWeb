import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useAllProjects, useSubprojects } from "@/api/meta";
import type { Project } from "@/api/types";
import { rankProjects } from "@/components/ProjectCombobox";
import type { Dashboard } from "@/features/dashboard/api";

export function CapturePickLabel({ project, sublabel }: { project: string; sublabel?: string }) {
  return <span className="capture-pick-label"><span className="text-red">{project}</span>{sublabel ? <span className="capture-pick-sub text-blue">{sublabel}</span> : null}</span>;
}

type Pick = { project: Project; subprojectIds: number[]; label: string; sublabel: string };

/** Recent project/subproject pairs and project search share one keyboard picker. */
export function CapturePicker({
  value,
  onChange,
  onStart,
  onHighlight,
  recent,
  id = "project-search",
  autoFocus = true,
  placeholder = "Search projects",
}: {
  value: Project | null;
  onChange: (project: Project | null, subprojectIds: number[]) => void;
  onStart?: (project: Project, subprojectIds: number[]) => void;
  onHighlight?: (project: Project | null, subprojectIds: number[]) => void;
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
    // Recents first, exactly as they were used; then every other project once.
    const unique = [...new Map(pairs.map((pair) => [`${pair.project.id}:${[...pair.subprojectIds].sort().join(",")}`, pair])).values()];
    const plain = new Set(unique.filter((pair) => !pair.subprojectIds.length).map((pair) => pair.project.id));
    const others = [...new Map([...unique.map((pair) => pair.project), ...rankProjects(all, text, 12)].map((project) => [project.id, project])).values()].filter((project) => !plain.has(project.id));
    const groups = new Map<number, Pick[]>();
    for (const pick of [...unique, ...others.map((project) => ({ project, subprojectIds: [], label: project.name, sublabel: "" }))]) groups.set(pick.project.id, [...(groups.get(pick.project.id) ?? []), pick]);
    return [...groups.values()].flatMap((group) => group.sort((a, b) => Number(!!a.sublabel) - Number(!!b.sublabel))).slice(0, 5);
  }, [projects.data, recent, text, exactProject, searchedSubs.data]);
  const highlight = open ? picks[active] : undefined;
  const highlightedKey = highlight ? `${highlight.project.id}:${highlight.subprojectIds.join(",")}` : "";
  const onHighlightRef = useRef(onHighlight); onHighlightRef.current = onHighlight;
  useEffect(() => { onHighlightRef.current?.(highlight?.project ?? null, highlight?.subprojectIds ?? []); }, [highlightedKey]);
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
                className={`${active === index ? "is-active" : ""}${pick.sublabel && picks[index - 1]?.project.id === pick.project.id ? " capture-pick-nested" : ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onPointerMove={() => setActive(index)}
                onClick={() => choose(pick)}
              >
                {pick.sublabel && picks[index - 1]?.project.id === pick.project.id ? <span className="capture-pick-label"><span className="capture-pick-sub text-blue">{pick.sublabel}</span></span> : <CapturePickLabel project={pick.label} sublabel={pick.sublabel || "no subproject"} />}
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
