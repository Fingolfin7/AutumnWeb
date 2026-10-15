import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { faArrowLeft, faCheckCircle } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useContexts } from "@/api/meta";
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
  const [values, setValues] = useState<ProjectValues>({ name: "", description: "", status: "active", context_id: null, tag_ids: [] });
  const [touchedContext, setTouchedContext] = useState(false);

  /* New projects default to the user's "General" context, as the old form did. */
  useEffect(() => {
    if (touchedContext) return;
    const general = contexts.data?.find((context) => context.name === "General");
    if (general) setValues((current) => (current.context_id === general.id ? current : { ...current, context_id: general.id }));
  }, [contexts.data, touchedContext]);

  const errors = splitErrors(create.error, FIELDS, "name");

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { ...values, name: values.name.trim() },
      {
        onSuccess: () => {
          toast.success("Project created successfully");
          navigate(urls.projects());
        },
        onError: (error) => {
          if (!splitErrors(error, FIELDS, "name").general.length) return;
          toast.error(failure("create the project", error));
        },
      },
    );
  };

  return (
    <>
      <PageHead title="New project" />
      <form className="fields" onSubmit={onSubmit}>
        <FormErrors errors={errors} />
        <section className="slab slab-pad">
          <ProjectFields
            values={values}
            onChange={(next) => {
              if (next.context_id !== values.context_id) setTouchedContext(true);
              setValues(next);
            }}
            errors={errors}
          />
        </section>
        <div className="form-actions">
          <AppLink className="btn btn--ghost" href={urls.projects()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
          <button className="btn btn--primary btn--spacer" type="submit" id="create-project" disabled={create.isPending}>
            <Icon icon={faCheckCircle} /> Create project
          </button>
        </div>
      </form>
    </>
  );
}
