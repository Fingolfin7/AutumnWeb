import { useMemo } from "react";
import { OptionPicker } from "@/components/OptionPicker";
import { Sheet } from "@/components/Sheet";
import type { Context, Project, Tag } from "@/api/types";
import type { SelectionFilters } from "./logic";

/* The narrowing controls that do not live on the page itself (the date range
   does): search, related, project name, context, note, tags and projects. */
export function FilterSheet({
  open,
  onClose,
  draft,
  onDraft,
  onApply,
  onClear,
  semantic,
  projects,
  tags,
  contexts,
  activeContextId,
}: {
  open: boolean;
  onClose: () => void;
  draft: SelectionFilters;
  onDraft: (next: SelectionFilters) => void;
  onApply: () => void;
  onClear: () => void;
  semantic: boolean;
  projects: Project[];
  tags: Tag[];
  contexts: Context[];
  activeContextId: number | null;
}) {
  /* The project picker narrows itself to the context and tags chosen beside
     it; a ticked project always stays visible. */
  const projectOptions = useMemo(() => {
    const scope = draft.context ? Number(draft.context) : activeContextId;
    return projects
      .filter((project) => {
        if (draft.projects.includes(project.id)) return true;
        if (scope !== null && project.context?.id !== scope) return false;
        if (draft.tags.length && !project.tags.some((tag) => draft.tags.includes(tag.id))) return false;
        return true;
      })
      .map((project) => ({ id: project.id, label: project.name }));
  }, [projects, draft.context, draft.tags, draft.projects, activeContextId]);

  return (
    <Sheet className="filter-sheet" open={open} onClose={onClose} title="Filter sessions">
      <div className="fields">
        <div className="field">
          <label htmlFor="content-search">Search projects, subprojects, and session notes</label>
          <input id="content-search" type="search" placeholder="Projects, subprojects, or notes" value={draft.search} onChange={(e) => onDraft({ ...draft, search: e.target.value })} />
        </div>

        {semantic ? (
          <div className="check-row">
            <input id="related-search" type="checkbox" checked={draft.related} onChange={(e) => onDraft({ ...draft, related: e.target.checked })} />
            <label htmlFor="related-search">Include related sessions</label>
          </div>
        ) : null}

        <div className="field">
          <label htmlFor="project-search">Project name</label>
          <input
            id="project-search"
            type="text"
            placeholder="Projects"
            autoComplete="off"
            list="insights-project-names"
            value={draft.project_name}
            onChange={(e) => onDraft({ ...draft, project_name: e.target.value })}
          />
          <datalist id="insights-project-names">
            {projects.map((project) => (
              <option key={project.id} value={project.name} />
            ))}
          </datalist>
        </div>

        <div className="field">
          <label htmlFor="context-filter">Context</label>
          <select id="context-filter" value={draft.context} onChange={(e) => onDraft({ ...draft, context: e.target.value })}>
            <option value="">Active context (header)</option>
            {contexts.map((ctx) => (
              <option key={ctx.id} value={ctx.id}>
                {ctx.name}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="note_snippet">Note contains</label>
          <input id="note_snippet" type="text" placeholder="Note Snippet" value={draft.note_snippet} onChange={(e) => onDraft({ ...draft, note_snippet: e.target.value })} />
        </div>

        {tags.length ? (
          <OptionPicker
            label="Tags"
            options={tags.map((t) => ({ id: t.id, label: t.name, color: t.color }))}
            selected={draft.tags}
            onChange={(ids) => onDraft({ ...draft, tags: ids })}
            emptyText="No tags match that search."
          />
        ) : null}

        {projects.length ? (
          <OptionPicker
            label="Projects"
            options={projectOptions}
            selected={draft.projects}
            onChange={(ids) => onDraft({ ...draft, projects: ids })}
            searchPlaceholder="Search projects..."
            emptyText="No projects match that search."
            mode={draft.projectMode}
            onModeChange={(mode) => onDraft({ ...draft, projectMode: mode })}
          />
        ) : null}

        <div className="sheet-foot">
          <button className="btn btn--ghost" type="button" onClick={onClear}>
            Clear all
          </button>
          <button className="btn btn--primary" type="button" onClick={onApply}>
            Apply filters
          </button>
        </div>
      </div>
    </Sheet>
  );
}
