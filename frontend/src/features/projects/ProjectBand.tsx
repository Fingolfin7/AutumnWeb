import { faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { formatDurationWords } from "@/lib/format";
import { useStartTimer } from "@/features/timers/api";
import type { Commitment, Project } from "@/api/types";

/* One project row (partials/project_band.html), also used by the Related
   section. Its primary action starts a timer on the project. */
export function ProjectBand({
  project,
  running,
  commitment,
  tagColors,
  weekMinutes,
}: {
  project: Project;
  weekMinutes?: number;
  running: boolean;
  /** The project's own active commitment, for the weekly summary. */
  commitment?: Commitment;
  tagColors: Map<number, string | null>;
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

        {project.context || project.tags.length ? (
          <div className="project-meta">
            {project.context ? (
              <AppLink className="context-chip" href={urls.updateContext(project.context.id)}>
                {project.context.name}
              </AppLink>
            ) : null}
            {project.tags.map((tag, index) => {
              const color = tagColors.get(tag.id);
              return (
                <AppLink
                  key={tag.id}
                  className={`tag-chip${index > 1 ? " project-tag-extra" : ""}`}
                  href={urls.updateTag(tag.id)}
                  style={color ? ({ "--tag": color } as React.CSSProperties) : undefined}
                >
                  {tag.name}
                </AppLink>
              );
            })}{project.tags.length > 2 ? <span className="chip project-tag-count">+{project.tags.length - 2}</span> : null}
          </div>
        ) : null}

        <p className="project-total"><span className="muted">This week</span><strong>{weekMinutes === undefined ? "Loading…" : formatDurationWords(weekMinutes)}</strong>{commitment && period ? <small className="muted">{commitment.period === "weekly" ? commitment.commitment_type === "time" ? `/ ${formatDurationWords(period.target)}` : `${Math.round(period.accrued)}/${Math.round(period.target)} sessions` : `${period.met ? "Met" : "In progress"} this period`}{period.met && commitment.period === "weekly" ? " · Met" : ""}</small> : null}</p>


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
