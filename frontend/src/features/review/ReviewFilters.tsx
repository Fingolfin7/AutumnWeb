import { useMemo, type ReactNode } from "react";
import { OptionPicker } from "@/components/OptionPicker";
import { Sheet } from "@/components/Sheet";
import { useActiveContext } from "@/app/context";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { SimilaritySlider } from "@/features/search/SimilaritySlider";
import { accountSimilarity, sameCutoff, similarityScale } from "@/features/search/similarity";
import { semanticSearchAvailable } from "@/features/charts/api";
import type { ChartFilters } from "@/features/charts/filters";

export function ReviewFilters({ open, onClose, draft, onChange, onClear, controls }: { open: boolean; onClose: () => void; draft: ChartFilters; onChange: (next: ChartFilters) => void; onClear: () => void; controls?: ReactNode }) {
  const projects = useAllProjects();
  const contexts = useContexts();
  const tags = useTags();
  const { contextId } = useActiveContext();
  const semantic = semanticSearchAvailable();
  const projectOptions = useMemo(() => {
    const scopeContext = draft.context === "all" ? null : draft.context ? Number(draft.context) : contextId;
    return (projects.data ?? [])
      .filter((project) => {
        if (draft.projects.includes(project.id)) return true;
        if (scopeContext !== null && project.context?.id !== scopeContext) return false;
        if (draft.tags.length && !project.tags.some((tag) => draft.tags.includes(tag.id))) return false;
        return true;
      })
      .map((project) => ({ id: project.id, label: project.name }));
  }, [projects.data, draft.context, draft.tags, draft.projects, contextId]);

  return <Sheet className="filter-sheet" open={open} onClose={onClose} title="Filter review">
    <div className="fields">
      <div className="review-filter-controls">{controls}</div>
      <p className="muted review-filter-status">Filters save automatically</p>
          <div className="field">
            <label htmlFor="content-search">Search projects, subprojects, and session notes</label>
            <input
              id="content-search"
              type="search"
              placeholder="Projects, subprojects, or notes"
              value={draft.search}
              onChange={(e) => onChange({ ...draft, search: e.target.value })}
            />
          </div>

          {semantic ? (
            <div className="check-row">
              <input id="related-search" type="checkbox" checked={draft.related} onChange={(e) => onChange({ ...draft, related: e.target.checked })} />
              <label htmlFor="related-search">Include related sessions</label>
            </div>
          ) : null}
          {semantic && draft.related ? (
            <SimilaritySlider
              value={draft.similarity ?? accountSimilarity()}
              defaultValue={accountSimilarity()}
              scale={similarityScale()}
              immediate
              onCommit={(value) =>
                onChange({ ...draft, similarity: sameCutoff(value, accountSimilarity()) ? null : value })
              }
            />
          ) : null}

          <div className="field">
            <label htmlFor="project-search">Project name (show subproject breakdown)</label>
            <input
              id="project-search"
              type="text"
              placeholder="Projects"
              autoComplete="off"
              list="project-names"
              value={draft.project_name}
              onChange={(e) => onChange({ ...draft, project_name: e.target.value })}
            />
            <datalist id="project-names">
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.name} />
              ))}
            </datalist>
          </div>

          <div className="field">
            <label htmlFor="context-filter">Context</label>
            <select id="context-filter" value={draft.context} onChange={(e) => onChange({ ...draft, context: e.target.value })}>
              <option value="">Current context</option>
              <option value="all">All contexts</option>
              {(contexts.data ?? []).map((ctx) => (
                <option key={ctx.id} value={ctx.id}>
                  {ctx.name}
                </option>
              ))}
            </select>
          </div>

          {tags.data?.length ? (
            <OptionPicker
              label="Tags"
              options={tags.data.map((t) => ({ id: t.id, label: t.name, color: t.color }))}
              selected={draft.tags}
              onChange={(ids) => onChange({ ...draft, tags: ids })}
              emptyText="No tags match that search."
            />
          ) : null}

          {projects.data?.length ? (
            <OptionPicker
              label="Projects"
              options={projectOptions}
              selected={draft.projects}
              onChange={(ids) => onChange({ ...draft, projects: ids })}
              searchPlaceholder="Search projects..."
              emptyText="No projects match that search."
              mode={draft.projectMode}
              onModeChange={(mode) => onChange({ ...draft, projectMode: mode })}
            />
          ) : null}

      <div className="sheet-foot">
        <button className="btn btn--quiet" type="button" onClick={onClear}>Clear filters</button>
        <button className="btn btn--secondary" type="button" onClick={onClose}>Done</button>
      </div>
    </div>
  </Sheet>;
}
