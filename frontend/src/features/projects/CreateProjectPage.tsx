import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { faArrowLeft, faCheckCircle, faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useContexts } from "@/api/meta";
import { useActiveContext } from "@/app/context";
import { api, unwrap } from "@/api/client";
import { useInvalidate } from "@/api/sync";
import { useStartTimer } from "@/features/timers/api";
import { errorMessage } from "@/api/errors";
import { failure, useCreateProject } from "./api";
import { splitErrors } from "./forms";
import type { ProjectValues } from "./logic";
import { FormErrors, PageHead, ProjectFields } from "./Parts";

const FIELDS = ["name", "description", "context_id", "tag_ids", "status"];

export default function CreateProjectPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const contexts = useContexts();
  const create = useCreateProject();
  const { contextId } = useActiveContext();
  const invalidate = useInvalidate();
  const start = useStartTimer();
  const [subprojects, setSubprojects] = useState([""]);
  const [created, setCreated] = useState<number | null>(null);
  const [savedSubs, setSavedSubs] = useState<{ id: number; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [values, setValues] = useState<ProjectValues>({ name: "", description: "", status: "active", context_id: null, tag_ids: [] });
  const [touchedContext, setTouchedContext] = useState(false);

  /* Follow the active context; General is the fallback when viewing all. */
  useEffect(() => {
    if (touchedContext) return;
    const general = contexts.data?.find((context) => context.id === contextId) ?? contexts.data?.find((context) => context.name === "General");
    if (general) setValues((current) => (current.context_id === general.id ? current : { ...current, context_id: general.id }));
  }, [contexts.data, contextId, touchedContext]);

  const errors = splitErrors(create.error, FIELDS, "name");

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const shouldStart = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("name") === "start";
    setBusy(true);
    setProblem("");
    let projectId = created;
    const subs = [...savedSubs];
    const names = subprojects.map((name) => name.trim()).filter(Boolean);
    setSubprojects(names.length ? names : [""]);
    try {
      if (!projectId) {
        const project = await create.mutateAsync({ ...values, name: values.name.trim() });
        projectId = project.id;
        setCreated(projectId);
      }
      for (const name of names.slice(subs.length)) {
        const sub = await unwrap(api.POST("/api/v2/projects/{project_id}/subprojects/", { params: { path: { project_id: projectId } }, body: { name, description: "" } }));
        subs.push({ id: sub.id, name: sub.name });
        setSavedSubs([...subs]);
      }
      invalidate("projects");
      if (shouldStart) await start.mutateAsync({ project_id: projectId, subproject_ids: subs.map((sub) => sub.id), optimistic: { projectName: values.name.trim(), subprojects: subs } });
      toast.success(shouldStart ? "Project created and timer started." : "Project created successfully");
      navigate(urls.updateProject(projectId));
    } catch (error) {
      setProblem(projectId ? `Your project is saved. ${errorMessage(error)} Retry to finish, or open the project.` : failure("create the project", error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead title="New project" />
      <form className="fields" onSubmit={onSubmit}>
        <FormErrors errors={errors} />
        {problem ? <div className="msg msg--error" role="alert">{problem}{created ? <AppLink href={urls.updateProject(created)}>Open project</AppLink> : null}</div> : null}
        <section className="slab slab-pad">
          <fieldset disabled={created !== null || busy} className="project-create-fields">
            <ProjectFields
              values={values}
              onChange={(next) => {
                if (next.context_id !== values.context_id) setTouchedContext(true);
                setValues(next);
              }}
              errors={errors}
            />
          </fieldset>
            <div className="field inline-subprojects">
              {subprojects.map((name, index) => <div className="field" key={index}><label htmlFor={`new-subproject-${index}`}>{index === 0 ? "Subproject (optional)" : `Subproject ${index + 1}`}</label><input id={`new-subproject-${index}`} disabled={busy || index < savedSubs.length} value={name} maxLength={255} placeholder="e.g. Field research" onChange={(event) => setSubprojects((current) => current.map((value, i) => i === index ? event.target.value : value))} /></div>)}
              <button className="btn btn--quiet" type="button" disabled={busy} onClick={() => setSubprojects([...subprojects, ""])}>Add another subproject</button>
            </div>
        </section>
        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={urls.projects()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--primary btn--spacer" type="submit" id="create-project" disabled={busy}>
            <Icon icon={faCheckCircle} /> Create project
          </button>
          <button className="btn btn--secondary" type="submit" name="start" disabled={busy}><Icon icon={faPlay} /> Create and start</button>
        </div>
      </form>
    </>
  );
}
