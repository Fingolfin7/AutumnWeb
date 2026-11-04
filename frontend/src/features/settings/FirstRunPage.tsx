import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useCreateProject } from "@/features/projects/api";
import { useStartTimer } from "@/features/timers/api";

export function EmptyWorkspace({ projects = false }: { projects?: boolean }) {
  return <section className="first-run-empty">
    <span className="ember-seal" aria-hidden="true" />
    <h1>{projects ? "Every project starts somewhere." : "Time for what matters."}</h1>
    <p>{projects ? "Give something you care about a place to grow." : "Start with one project. Your time and the story behind it will find a home here."}</p>
    <AppLink className="btn btn--primary btn--lg" href="/welcome/">Create your first project</AppLink>
  </section>;
}

export default function FirstRunPage() {
  const create = useCreateProject();
  const start = useStartTimer();
  const { contextId } = useActiveContext();
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState("");
  const [project, setProject] = useState<{ id: number; name: string } | null>(null);
  const [error, setError] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || create.isPending) return;
    setError("");
    create.mutate({ name: name.trim(), context_id: contextId, description: "", status: "active", tag_ids: [] }, {
      onSuccess: (created) => setProject(created),
      onError: (failure) => setError(errorMessage(failure)),
    });
  };
  return <section className="first-run-page slab slab-pad">
    <ol className="first-run-steps" aria-label="Getting started"><li aria-current={!project ? "step" : undefined}>Create a project</li><li aria-current={project ? "step" : undefined}>Start a timer</li><li>See your day</li></ol>
    <span className="ember-seal" aria-hidden="true" />
    <h1 className="page-title">{project ? "A little time. A beginning." : "What would you like to make time for?"}</h1>
    <p>{project ? `${project.name} is ready. Start now, and add a note whenever a thought comes along.` : "A project can be anything you return to: learning a language, building something, or simply reading."}</p>
    {error ? <p className="errorlist" role="alert">{error}</p> : null}
    {project ? <div className="first-run-actions"><button className="btn btn--primary btn--lg" disabled={start.isPending} onClick={() => start.mutate({ project_id: project.id, subproject_ids: [], optimistic: { projectName: project.name, subprojects: [] } }, {
      onSuccess: () => { toast.success(`Started ${project.name}. Your day has begun.`); navigate(urls.home()); },
      onError: (failure) => setError(errorMessage(failure)),
    })}>{start.isPending ? "Starting…" : `Start ${project.name}`}</button><AppLink className="btn btn--quiet" href={urls.updateProject(project.id)}>I'll start later</AppLink></div> : <form className="fields" onSubmit={submit}>
      <div className="field"><label htmlFor="first-project-name">Project name</label><input id="first-project-name" type="text" autoFocus autoComplete="off" maxLength={100} placeholder="Something worth your time" required value={name} onChange={(event) => setName(event.target.value)} /></div>
      <button type="submit" className="btn btn--primary btn--lg" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create project"}</button>
    </form>}
  </section>;
}
