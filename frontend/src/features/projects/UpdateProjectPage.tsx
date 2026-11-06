import { useMemo, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { faEllipsisH, faStop, faCheckCircle, faCodeBranch, faPlay, faPen, faPlus, faSitemap, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Select } from "@/components/ui";
import { Sheet } from "@/components/Sheet";
import { SessionBand } from "@/features/sessions/SessionBand";
import { SessionNote } from "@/components/SessionNote";
import { useSessionList, useSessionTotals } from "@/features/sessions/api";

import { useNow, useStartTimer, useTimers } from "@/features/timers/api";
import { bootstrap } from "@/bootstrap";
import { addDays, todayKey } from "@/features/notifications/dates";
import { calendarWeek } from "@/features/review/periods";
import { useChartData } from "@/features/charts/api";
import type { DailyTotalRow } from "@/features/charts/payloads";
import { Disclose } from "@/components/Disclose";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { elapsedSeconds, formatClock, formatDate, formatDurationWords } from "@/lib/format";
import { groupByDay } from "@/lib/sessions";
import type { Project, ProjectDetail } from "@/api/types";
import { useCommitmentsAppliedTo } from "@/features/commitments/api";
import { failure, useProject, useUpdateProject } from "./api";
import { CommitmentSummary } from "@/features/commitments/CommitmentSummary";
import { CommitmentsPanel } from "./CommitmentsPanel";
import { conflictCurrent, splitErrors } from "./forms";
import { changedFields, type ProjectValues } from "./logic";
import { ConflictBanner, FormErrors, LoadState, PageHead, ProjectFields } from "./Parts";

const FIELDS = ["name", "description", "status", "context_id", "tag_ids"];

const toValues = (project: ProjectDetail): ProjectValues => ({
  name: project.name,
  description: project.description,
  status: project.status,
  context_id: project.context?.id ?? null,
  tag_ids: project.tags.map((tag) => tag.id),
});

export default function UpdateProjectPage() {
  const projectId = Number(useParams().projectId);
  const project = useProject(projectId);
  return <LoadState query={project}>{project.data ? <ProjectDetailView key={projectId} project={project.data} /> : null}</LoadState>;
}

function ProjectDetailView({ project }: { project: ProjectDetail }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const start = useStartTimer();
  const recent = useSessionList({ project_ids: String(project.id) });
  const weekStart = calendarWeek(todayKey(bootstrap().profile.timezone)).start;
  const week = useSessionTotals({ project_ids: String(project.id), start_date: weekStart, end_date: addDays(weekStart,6) });
  const lastWeek = useSessionTotals({ project_ids: String(project.id), start_date: addDays(weekStart,-7), end_date: addDays(weekStart,-1) });
  const trend = useChartData({ chart_type: "calendar", include_projects: [project.id], start_date: addDays(weekStart,-7), end_date: addDays(weekStart,6), context: "all" }, true);
  const timers = useTimers();
  const now = useNow();
  const running = (timers.data ?? []).filter(timer => timer.project.id === project.id);
  const [selectedSub, setSelectedSub] = useState("");
  const [subMenu, setSubMenu] = useState<number | null>(null);
  const recentRows = recent.data?.pages[0]?.sessions.slice(0,5) ?? [];
  const journalDays = groupByDay(recentRows);
  const update = useUpdateProject(project.id);
  const related = useCommitmentsAppliedTo("project", project.id).data ?? [];
  const ownCommitment = related.find((item) => item.active && item.aggregation_type === "project" && item.target.id === project.id) ?? related.find((item) => item.aggregation_type === "project" && item.target.id === project.id);
  /* The project as the form was opened (or last saved/reloaded): the edit is
     diffed against it and the PATCH carries its version (If-Match). */
  const [baseline, setBaseline] = useState(project);
  const [values, setValues] = useState<ProjectValues>(() => toValues(project));
  const [conflict, setConflict] = useState<Project | null>(null);
  const errors = splitErrors(conflict ? null : update.error, FIELDS, "name");
  const changedElsewhere = project.version !== baseline.version;

  const reset = (from: ProjectDetail) => {
    setBaseline(from);
    setValues(toValues(from));
    setConflict(null);
    update.reset();
  };

  const knownSubprojects = useMemo(() => new Map(project.subprojects.map((sub) => [sub.id, sub.name] as const)), [project.subprojects]);

  const save = (patch: Partial<ProjectValues>, version: number | undefined) => {
    update.mutate(
      { patch, version },
      {
        onSuccess: (saved) => {
          setBaseline((current) => ({ ...current, ...saved }));
          setConflict(null);
          setEditing(false);
          setValues((current) => ({ ...current, name: saved.name }));
          /* The server words it (core/services/celebrations.py), the same as
             the CLI and MCP see. */
          if (saved.celebration) {
            toast.success(saved.celebration.message, { celebration: "completion" });
          } else {
            toast.success("Project updated successfully");
          }
        },
        onError: (error) => {
          const current = conflictCurrent<Project>(error);
          if (current) setConflict(current);
          else if (splitErrors(error, FIELDS, "name").general.length) toast.error(failure("save the project", error));
        },
      },
    );
  };

  const changes = () => changedFields(toValues(baseline), { ...values, name: values.name.trim() });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const patch = changes();
    if (!Object.keys(patch).length) {
      toast.info("Nothing to save.");
      return;
    }
    save(patch, baseline.version);
  };

  return (
    <>
      <div className="project-overview">
        <div className="desk-head project-page-head">
          <PageHead title={project.name} titleClass="text-red" />
          <button type="button" className="btn btn--quiet" onClick={() => { reset(project); setEditing(true); }}><Icon icon={faPen} /> Edit project</button>
        </div>
        <div className="project-properties" aria-label="Project properties"><span className="chip">{project.status}</span>{project.context ? <AppLink className="chip-link" href={urls.updateContext(project.context.id)}><span className="context-chip">{project.context.name}</span></AppLink> : null}{project.tags.map(tag => <AppLink className="chip-link" key={tag.id} href={urls.updateTag(tag.id)}><span className="tag-chip">{tag.name}</span></AppLink>)}<a href="#project-subprojects">{project.subprojects.length} subproject{project.subprojects.length === 1 ? "" : "s"}</a>{ownCommitment ? <a href="#project-commitment">Commitment</a> : null}<span>{formatDurationWords(project.total_minutes)} total · {project.session_count} sessions</span></div>
        <div className="project-start-control fields">
          {project.subprojects.length && !running.length ? <><label className="sr-only" htmlFor="project-subproject-picker">Subproject</label><Select id="project-subproject-picker" value={selectedSub} onChange={event => setSelectedSub(event.target.value)}><option value="">No subproject</option>{project.subprojects.map(sub => <option key={sub.id} value={sub.id}>{sub.name}</option>)}</Select></> : null}
          {running.length ? <div className="project-live-card"><span className="live-dot" /><strong>{formatClock(elapsedSeconds(running[0]!.start, now))}</strong>{running[0]!.note ? <span className="project-running-note">{running[0]!.note}</span> : null}<AppLink className="btn btn--stop" href={urls.stopTimer(running[0]!.id)}><Icon icon={faStop} /> Stop{running.length > 1 ? ` (${running.length})` : ""}</AppLink></div> : <button className="btn btn--primary" type="button" disabled={start.isPending} onClick={() => { const sub = project.subprojects.find(item => item.id === Number(selectedSub)); start.mutate({ project_id: project.id, subproject_ids: sub ? [sub.id] : [], optimistic: { projectName: project.name, subprojects: sub ? [{ id: sub.id, name: sub.name }] : [] } }, { onSuccess: () => toast.success(`Started ${sub?.name ?? project.name}.`), onError: error => toast.error(failure("start the timer", error)) }); }}><Icon icon={faPlay} /> Start timer</button>}
        </div>
        <div className="project-progress-row"><section className="project-week-summary"><h2>This week</h2><strong>{week.data ? formatDurationWords(week.data.total_minutes) : "…"}</strong><p className="muted">{week.data && lastWeek.data ? week.data.total_minutes === lastWeek.data.total_minutes ? "Same as last week" : `${week.data.total_minutes > lastWeek.data.total_minutes ? "+" : "−"}${formatDurationWords(Math.abs(week.data.total_minutes-lastWeek.data.total_minutes))} from last week` : "Comparing weeks…"}</p>{trend.data ? <ProjectTrend rows={trend.data.data as DailyTotalRow[]} start={addDays(weekStart,-7)} /> : null}</section><section className="project-week-target" id="project-commitment">{ownCommitment ? <><h2>Commitment</h2><CommitmentSummary commitment={ownCommitment} showTarget={false} /></> : <AppLink className="btn btn--quiet" href={urls.createCommitment(project.id)}><Icon icon={faPlus} /> Add commitment</AppLink>}</section></div>
        {project.description ? <details className="project-description"><summary>About this project</summary><SessionNote text={project.description} /></details> : null}
        <Sheet open={editing} onClose={() => setEditing(false)} title="Edit project" className="project-edit-sheet">

        {conflict || changedElsewhere ? (
          <ConflictBanner
            noun="project"
            outcome={conflict ? "Your changes were not saved." : undefined}
            onLoadLatest={() => reset(conflict ? { ...project, ...conflict } : project)}
            onSaveAnyway={conflict ? () => save(changes(), conflict.version) : undefined}
            busy={update.isPending}
          />
        ) : null}


          <form className="fields" onSubmit={onSubmit}>
            <FormErrors errors={errors} />
            <section>
              <p className="muted project-history">Created {formatDate(project.start_date)}. Last active {formatDate(project.last_activity) || "never"}. Average session {formatDurationWords(project.session_count ? project.total_minutes / project.session_count : 0)}.</p>
              <ProjectFields values={values} onChange={setValues} errors={errors} showStatus />
              <div className="form-actions">
                <button className="btn btn--primary" type="submit" id="update-project" disabled={update.isPending}>
                  <Icon icon={faCheckCircle} /> Save changes
                </button>
                <AppLink className="btn btn--danger btn--spacer" href={urls.deleteProject(project.id)}>
                  <Icon icon={faTrash} /> Delete project
                </AppLink>
                <AppLink className="btn btn--quiet" href={urls.mergeProjects()}><Icon icon={faCodeBranch} /> Merge projects</AppLink>
              </div>
            </section>
          </form>

        </Sheet>


        <section className="session-list project-journal" aria-label="Recent journal entries">
          <div className="project-journal-link"><h2>Journal</h2><AppLink className="text-link" href={`${urls.sessions()}?include_projects=${project.id}`}>All sessions</AppLink></div>
          {recent.isError ? <p className="slab-pad muted">Could not load journal entries. <button type="button" className="btn btn--quiet" onClick={() => void recent.refetch()}>Try again</button></p> : recent.isPending ? <p className="slab-pad muted">Loading entries…</p> : recent.data?.pages[0]?.sessions.length ? <>{journalDays.map(group => <section className="project-journal-day" key={group.date}><header className="day-head"><h3 className="day-date">{formatDate(group.date)}</h3><strong className="day-total">{formatDurationWords(group.totalMinutes)}</strong></header><ul className="band-list">{group.sessions.map(session => <SessionBand key={session.id} session={session} day={group.date} hideProject />)}</ul></section>)}</> : <p className="empty">Your first session will appear here.</p>}
        </section>
        <aside className="project-rail">
        <Disclose id="project-subprojects" icon={faSitemap} iconClass="text-blue" title="Subprojects" summary={project.subprojects.length}>
          {project.subprojects.length ? (
            <ul className="band-list">
              {project.subprojects.map((sub) => { return (
                <li className="band project" id={`subproject-${sub.id}`} key={sub.id}>
                  <div className="u-grow">
                    <div className="project-top">
                      <AppLink className="project-name text-blue" href={urls.updateSubproject(sub.id)}>
                        {sub.name}
                      </AppLink>
                    </div>
                    <p className="project-total">{formatDurationWords(sub.total_minutes)}</p>
                    {sub.total_minutes > 0 && sub.last_activity ? <p className="project-dates">Last active {formatDate(sub.last_activity)}</p> : null}
                  </div>
                  <div className="u-row u-gap-2">
                    <button className="btn-icon" type="button" aria-label={`More actions for ${sub.name}`} onClick={() => setSubMenu(sub.id)}><Icon icon={faEllipsisH} /></button>
                    <Sheet open={subMenu === sub.id} onClose={() => setSubMenu(null)} title={sub.name}>
                    <AppLink className="btn btn--quiet" href={urls.updateSubproject(sub.id)} title="Edit subproject">
                      <Icon icon={faPen} />
                      <span>Edit subproject</span>
                    </AppLink>
                    <AppLink className="btn btn--quiet btn-icon--danger" href={urls.deleteSubproject(sub.id)} title="Delete subproject">
                      <Icon icon={faTrash} />
                      <span>Delete subproject</span>
                    </AppLink>
                    </Sheet>
                  </div>
                </li>
              ); })}
            </ul>
          ) : (
            <p className="empty">No subprojects yet.</p>
          )}

          <div className="slab-foot action-row">
            <AppLink className="btn btn--secondary" href={urls.createSubproject(project.id)}>
              <Icon icon={faPlus} /> New subproject
            </AppLink>
            {project.subprojects.length ? (
              <AppLink className="btn btn--ghost" href={urls.mergeSubprojects(project.id)}>
                <Icon icon={faCodeBranch} /> Merge
              </AppLink>
            ) : null}
          </div>
        </Disclose>
        {related.some((item) => item.id !== ownCommitment?.id) ? <CommitmentsPanel commitments={related.filter((item) => item.id !== ownCommitment?.id)} addUrl={urls.createCommitment(project.id)} entityLabel="project" knownSubprojects={knownSubprojects} /> : null}

        </aside>
      </div>
    </>
  );
}

function ProjectTrend({ rows, start }: { rows: DailyTotalRow[]; start: string }) {
  if (rows.filter(row => Number(row.hours) > 0).length < 2) return null;
  const values = new Map(rows.map(row => [row.date, Number(row.hours)])); const max = Math.max(1,...values.values());
  return <><svg className="project-trend" viewBox="0 0 280 72" role="img" aria-label="Daily time over the previous and current weeks">{Array.from({ length:14 },(_,index) => <rect key={index} x={index * 20} y={70 - (values.get(addDays(start,index)) ?? 0) / max * 64} width="13" height={(values.get(addDays(start,index)) ?? 0) / max * 64} rx="2" className={index < 7 ? "is-previous" : undefined}><title>{formatDate(addDays(start,index))}: {formatDurationWords((values.get(addDays(start,index)) ?? 0) * 60)}</title></rect>)}</svg><p className="muted">Last week / this week</p></>;
}
