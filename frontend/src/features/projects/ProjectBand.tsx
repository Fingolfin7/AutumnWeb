import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { formatDurationWords, formatDate } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import type { Commitment, Project } from "@/api/types";

/* One project row (partials/project_band.html), also used by the Related
   section. Its primary action starts a timer on the project. */
export function ProjectBand({
  project,
  running,
  commitment,
  weekMinutes,
  trend,
  latestNote,
}: {
  project: Project;
  weekMinutes?: number;
  trend?: number[];
  latestNote?: string | null;
  running: boolean;
  /** The project's own active commitment, for the weekly summary. */
  commitment?: Commitment;
}) {
  const start = useStartTimer();
  const toast = useToast();
  const label = running
    ? `Start another timer on ${project.name}, one is already running`
    : `Start a timer on ${project.name}`;

  const onStart = () =>
    start.mutate(
      { project_id: project.id, optimistic: { projectName: project.name, subprojects: [] } },
      {
        onSuccess: () => toast.success(`Started ${project.name}.`),
        onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
      },
    );

  const period = commitment?.current_period;
  return (
    <li className="band project project-directory-row" id={`project-${project.id}`}>
      <div className="u-grow">
        <div className="project-top">
          <AppLink className="project-name text-red" href={urls.updateProject(project.id)}>
            {project.name}
          </AppLink>
          {running ? (
            <AppLink className="project-running" href={urls.timers()} title="A timer is already running on this project">
              <span className="live-dot" /> running
            </AppLink>
          ) : null}
        </div>

        <div className="project-directory-preview"><span>{project.last_activity ? `Last worked ${formatDate(project.last_activity)}` : "No sessions yet"}</span>{latestNote ? <AppLink href={urls.updateProject(project.id)} className="project-note-line">{latestNote.replace(/<[^>]*>/g, " ").replace(/[#*_`]/g, "").split(/\r?\n/).find(line => line.trim())}</AppLink> : <span>{project.context?.name ?? ""}{project.tags.length ? ` · ${project.tags.map(tag => tag.name).join(", ")}` : ""}</span>}</div>
        {trend ? <svg className="project-week-spark" viewBox="0 0 112 32" role="img" aria-label="Weekly time over eight weeks">{trend.map((minutes, index) => <rect key={index} x={index * 14} y={30 - minutes / Math.max(...trend,1) * 28} width="9" height={Math.max(1,minutes / Math.max(...trend,1) * 28)} rx="2"><title>{index === 7 ? "This week" : `${7-index} weeks ago`}: {formatDurationWords(minutes)}</title></rect>)}</svg> : null}
        <p className="project-total"><strong>{weekMinutes === undefined ? "Loading…" : formatDurationWords(weekMinutes)}</strong>{commitment && period ? <small className="muted">{commitment.period === "weekly" ? commitment.commitment_type === "time" ? `/ ${formatDurationWords(period.target)}` : `${Math.round(period.accrued)}/${Math.round(period.target)} sessions` : `${period.met ? "Met" : "In progress"} this period`}{period.met && commitment.period === "weekly" ? " · Met" : ""}</small> : null}</p>


      </div>

      <button
        className={`project-start${running ? " is-running" : ""}`}
        type="button"
        title={running ? `Start ANOTHER timer on ${project.name} — one is already running` : `Start a timer on ${project.name}`}
        onClick={onStart}
        disabled={start.isPending}
      >
        <Icon icon={faPlay} />
        <span className="sr-only">{label}</span>
      </button>
    </li>
  );
}
