import { useId, useMemo, useRef, useState } from "react";
import { useAllProjects } from "@/api/meta";
import type { Project } from "@/api/types";

/* Rank projects for a typed query: exact name, then prefix, then word
   prefix, then substring; active projects before paused/complete/archived
   within each band; then by name. */
export function rankProjects(projects: Project[], query: string, limit = 8): Project[] {
  const needle = query.trim().toLowerCase();
  const statusRank: Record<string, number> = { active: 0, paused: 1, complete: 2, archived: 3 };
  const scored: { project: Project; band: number }[] = [];
  for (const project of projects) {
    const name = project.name.toLowerCase();
    let band: number;
    if (!needle) band = 3;
    else if (name === needle) band = 0;
    else if (name.startsWith(needle)) band = 1;
    else if (name.split(/[\s\-_/]+/).some((word) => word.startsWith(needle))) band = 2;
    else if (name.includes(needle)) band = 3;
    else continue;
    scored.push({ project, band });
  }
  scored.sort(
    (a, b) =>
      a.band - b.band ||
      (statusRank[a.project.status] ?? 9) - (statusRank[b.project.status] ?? 9) ||
      a.project.name.localeCompare(b.project.name),
  );
  return scored.slice(0, limit).map((entry) => entry.project);
}

/* A project picker with the old jQuery-UI autocomplete's look
   (.ui-autocomplete / .ui-menu-item-wrapper in focus_desk.css), filtering
   locally over the cached project list: no request per keystroke. Typing a
   name that exactly matches a project selects it. */
export function ProjectCombobox({
  id,
  value,
  onChange,
  placeholder = "Start typing a project name...",
  autoFocus,
  invalid,
}: {
  id: string;
  value: Project | null;
  /* Also given the typed text, for forms that validate unmatched input. */
  onChange: (project: Project | null, text: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  invalid?: boolean;
}) {
  const projects = useAllProjects();
  const [text, setText] = useState(value?.name ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);

  /* Follow external changes (prefill from a URL, a reset). */
  const [lastValue, setLastValue] = useState(value);
  if (value !== lastValue) {
    setLastValue(value);
    if (value && value.name !== text) setText(value.name);
  }

  const matches = useMemo(() => rankProjects(projects.data ?? [], text), [projects.data, text]);

  const choose = (project: Project) => {
    setText(project.name);
    setOpen(false);
    onChange(project, project.name);
  };

  const type = (next: string) => {
    setText(next);
    setOpen(true);
    setActive(0);
    const exact = (projects.data ?? []).find((p) => p.name.toLowerCase() === next.trim().toLowerCase());
    onChange(exact ?? null, next);
  };

  return (
    <div className="combobox" style={{ position: "relative" }}>
      <input
        ref={input}
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches[active] ? `${listId}-${matches[active]!.id}` : undefined}
        autoComplete="off"
        autoFocus={autoFocus}
        aria-invalid={invalid || undefined}
        placeholder={placeholder}
        value={text}
        onMouseDown={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onChange={(event) => type(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActive((index) => Math.min(index + 1, Math.max(0, matches.length - 1)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) => Math.max(index - 1, 0));
          } else if (event.key === "Enter") {
            if (open && matches[active]) {
              event.preventDefault();
              choose(matches[active]!);
            }
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {/* #project-search-results lets the enclosing .slab stop clipping the
          list (focus_desk.css: .slab:has(#project-search-results)). */}
      <div id="project-search-results">
      {open && matches.length > 0 ? (
        <ul className="ui-autocomplete ui-menu" id={listId} role="listbox" style={{ left: 0, right: 0 }}>
          {matches.map((project, index) => (
            <li className="ui-menu-item" key={project.id} role="option" id={`${listId}-${project.id}`} aria-selected={index === active}>
              <div
                className={`ui-menu-item-wrapper${index === active ? " ui-state-active" : ""}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(project);
                }}
                onMouseEnter={() => setActive(index)}
              >
                {project.name}
                {project.status !== "active" ? <span className="muted"> · {project.status}</span> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      </div>
    </div>
  );
}
