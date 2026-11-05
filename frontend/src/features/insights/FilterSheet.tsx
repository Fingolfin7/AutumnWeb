import { useEffect, useMemo, useState, type ReactNode } from "react";
import { bootstrap } from "@/bootstrap";
import { todayKey } from "@/features/notifications/dates";
import { presetPeriod } from "@/features/review/periods";
import { DateInput, SegmentedControl } from "@/components/ui";
import { useInsightSelection } from "./api";
import { selectionQuery } from "./logic";
import { OptionPicker } from "@/components/OptionPicker";
import { Sheet } from "@/components/Sheet";
import type { Context, Project, Tag } from "@/api/types";
import { SimilaritySlider } from "@/features/search/SimilaritySlider";
import { accountSimilarity, sameCutoff, similarityScale } from "@/features/search/similarity";
import type { SelectionFilters } from "./logic";

/* One place for the conversation's dates, model and session filters. */
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
  children,
  defaults,
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
  children?: ReactNode;
  defaults: { start: string; end: string };
}) {
  const [searchField, setSearchField] = useState<"search" | "project_name" | "note_snippet">("search");
  const [countDraft, setCountDraft] = useState(draft);
  useEffect(() => { const timer = window.setTimeout(() => setCountDraft(draft), 350); return () => window.clearTimeout(timer); }, [draft]);
  const matches = useInsightSelection(selectionQuery(countDraft, defaults, activeContextId), open);
  const today = todayKey(bootstrap().profile.timezone);
  /* The project picker narrows itself to the context and tags chosen beside
     it; a ticked project always stays visible. */
  const projectOptions = useMemo(() => {
    const scope = draft.context === "all" ? null : draft.context ? Number(draft.context) : activeContextId;
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
    <Sheet className="filter-sheet insights-filter-sheet" open={open} onClose={onClose} title="Conversation context">
      <div className="fields">
        <SegmentedControl label="Session dates" value={["week", "last", "month"].find(value => { const range = presetPeriod(value as "week" | "last" | "month", today); return draft.start_date === range.start && draft.end_date === range.end; }) ?? "custom"} options={[{ value: "week", label: "This week" }, { value: "last", label: "Last week" }, { value: "month", label: "30 days" }]} onChange={value => { const range = presetPeriod(value as "week" | "last" | "month", today); onDraft({ ...draft, start_date: range.start, end_date: range.end }); }} />
        <div className="two-up"><div className="field"><label htmlFor="start_date">Start date</label><DateInput presets="none" today={today} id="start_date" value={draft.start_date} onValueChange={value => onDraft({ ...draft, start_date: value })} /></div><div className="field"><label htmlFor="end_date">End date</label><DateInput presets="none" today={today} id="end_date" value={draft.end_date} onValueChange={value => onDraft({ ...draft, end_date: value })} /></div></div>
        <div className="field"><label htmlFor="content-search">Find sessions</label><div className="insights-search"><input id="content-search" type="search" placeholder="Search your time" value={draft[searchField]} onChange={event => onDraft({ ...draft, [searchField]: event.target.value })} /><select aria-label="Search in" value={searchField} onChange={event => setSearchField(event.target.value as typeof searchField)}><option value="search">Everything</option><option value="project_name">Project names</option><option value="note_snippet">Notes</option></select></div></div>
        {(["search", "project_name", "note_snippet"] as const).filter(key => key !== searchField && draft[key]).map(key => <button className="btn btn--quiet" type="button" key={key} onClick={() => onDraft({ ...draft, [key]: "" })}>{key === "project_name" ? "Project" : key === "note_snippet" ? "Note" : "Search"}: {draft[key]} - Clear</button>)}
        {semantic ? (
          <div className="check-row">
            <input id="related-search" type="checkbox" checked={draft.related} onChange={(e) => onDraft({ ...draft, related: e.target.checked })} />
            <label htmlFor="related-search">Include related sessions</label>
          </div>
        ) : null}
        {semantic && draft.related ? (
          <SimilaritySlider
            value={draft.similarity ?? accountSimilarity()}
            defaultValue={accountSimilarity()}
            scale={similarityScale()}
            immediate
            onCommit={(value) => onDraft({ ...draft, similarity: sameCutoff(value, accountSimilarity()) ? null : value })}
          />
        ) : null}

        <div className="field">
          <label htmlFor="context-filter">Context</label>
          <select id="context-filter" value={draft.context} onChange={(e) => onDraft({ ...draft, context: e.target.value })}>
            <option value="">Current context</option>
            <option value="all">All contexts</option>
            {contexts.map((ctx) => (
              <option key={ctx.id} value={ctx.id}>
                {ctx.name}
              </option>
            ))}
          </select>
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

        {children}
        <div className="sheet-foot insights-context-apply"><span role="status">{matches.isFetching || JSON.stringify(countDraft) !== JSON.stringify(draft) ? "Counting sessions" : matches.isError ? "Count unavailable" : `${matches.data?.count ?? 0} matching sessions`}</span>
          <button className="btn btn--ghost" type="button" onClick={onClear}>
            Clear all
          </button>
          <button className="btn btn--primary" type="button" onClick={onApply}>
            Use context
          </button>
        </div>
      </div>
    </Sheet>
  );
}
