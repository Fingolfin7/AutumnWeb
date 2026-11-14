import { useEffect, useState } from "react";
import { ProjectCombobox } from "@/components/ProjectCombobox";
import { FieldErrors } from "@/features/contexts-tags/ui";
import { useAllProjects, useSubprojects } from "@/api/meta";
import type { Project } from "@/api/types";

/* The project + subprojects choice shared by both modes of the New timer
   page, so switching between "start now" and "log past" keeps it.
   ?project_id=&subproject_id= prefill it (notification action links use
   this). */
export function useProjectPick(params: URLSearchParams) {
  const projects = useAllProjects();
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const subprojects = useSubprojects(project?.id);

  /* Prefill once the project list is in. */
  const [prefilled, setPrefilled] = useState(false);
  useEffect(() => {
    if (prefilled || !projects.data) return;
    setPrefilled(true);
    const projectId = Number(params.get("project_id"));
    const initial = projects.data.find((p) => p.id === projectId);
    if (initial) {
      setProject(initial);
      setSelected(params.getAll("subproject_id").map(Number).filter((n) => Number.isInteger(n) && n > 0));
    }
  }, [params, prefilled, projects.data]);

  const subs = subprojects.data ?? [];
  return {
    project,
    selected,
    setSelected,
    subprojects,
    subs,
    /** The selected subprojects that belong to the project. */
    chosen: subs.filter((s) => selected.includes(s.id)),
    pickProject: (next: Project | null) => {
      if (next?.id !== project?.id) setSelected([]);
      setProject(next);
    },
  };
}

export type ProjectPick = ReturnType<typeof useProjectPick>;

export function ProjectFields({ pick, autoFocus, error }: { pick: ProjectPick; autoFocus: boolean; error?: string[] }) {
  const { project, selected, setSelected, subprojects, subs } = pick;
  const allChecked = subs.length > 0 && subs.every((s) => selected.includes(s.id));
  return (
    <section className="slab slab-pad">
      <div className="field" id="search-projects">
        <label htmlFor="project-search">Project</label>
        <ProjectCombobox id="project-search" value={project} onChange={pick.pickProject} autoFocus={autoFocus} />
        <FieldErrors errors={error} />
      </div>
      {project ? (
        <section id="pick-subprojects" className="field">
          <div className="field-head" id="select-all-block">
            <span className="field-label">Subprojects</span>
            {subs.length ? (
              <span className="select-all-row">
                <input
                  type="checkbox"
                  id="select-all"
                  className="select-all"
                  checked={allChecked}
                  onChange={() => setSelected(allChecked ? [] : subs.map((s) => s.id))}
                />
                <label htmlFor="select-all">All</label>
              </span>
            ) : null}
          </div>
          <div className="check-grid" id="subproject_options">
            {subprojects.isPending ? (
              <span className="subproject-empty-state">Loading...</span>
            ) : subprojects.isError ? (
              <span className="subproject-empty-state">Could not load subprojects.</span>
            ) : subs.length ? (
              subs.map((sub) => (
                <span className="subproject-option" key={sub.id}>
                  <input
                    type="checkbox"
                    id={`subproject-option-${sub.id}`}
                    checked={selected.includes(sub.id)}
                    onChange={() =>
                      setSelected((current) => (current.includes(sub.id) ? current.filter((id) => id !== sub.id) : [...current, sub.id]))
                    }
                  />
                  <label htmlFor={`subproject-option-${sub.id}`}>{sub.name}</label>
                </span>
              ))
            ) : (
              <span className="subproject-empty-state">No subprojects found.</span>
            )}
          </div>
        </section>
      ) : null}
    </section>
  );
}
