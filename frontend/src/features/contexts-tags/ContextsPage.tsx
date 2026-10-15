import { useState, type FormEvent } from "react";
import { faPlus } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useContexts } from "@/api/meta";
import { useCreateContext } from "./api";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "./formErrors";
import { validateName } from "./stats";
import { DeskHead, FieldErrors, FormLevelErrors } from "./ui";

/* Contexts list + create form (templates/core/contexts.html). */
export default function ContextsPage() {
  const contexts = useContexts();
  const create = useCreateContext();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problem = validateName(name, "context", contexts.data ?? []);
    if (problem) {
      setErrors({ fields: { name: [problem] }, general: [] });
      return;
    }
    setErrors(NO_ERRORS);
    create.mutate(
      { name: name.trim(), description: description.trim() || null },
      {
        onSuccess: () => {
          toast.success("Context created successfully");
          setName("");
          setDescription("");
        },
        onError: (error) => setErrors(parseFormErrors(error, { conflictField: "name" })),
      },
    );
  };

  return (
    <>
      <DeskHead title="Contexts" />
      <div className="split">
        <section id="contexts-list" className="slab" aria-label="Contexts">
          {contexts.isPending ? (
            <Skeleton lines={4} />
          ) : contexts.isError ? (
            <ErrorState error={contexts.error} onRetry={() => void contexts.refetch()} />
          ) : contexts.data.length ? (
            <ul className="band-list">
              {contexts.data.map((ctx) => (
                <li key={ctx.id} className="band band--tap">
                  <AppLink className="context-chip" href={urls.updateContext(ctx.id)}>
                    {ctx.name}
                  </AppLink>
                  {ctx.description ? <p className="muted u-mt-4">{ctx.description}</p> : null}
                </li>
              ))}
            </ul>
          ) : (
            <Empty>
              No contexts yet. <a href="#create-context">Create one</a> to group projects by setting.
            </Empty>
          )}
        </section>

        <form className="fields" id="create-context" onSubmit={submit} noValidate>
          <FormLevelErrors errors={errors.general} />
          <section className="slab slab-pad">
            <div className="field">
              <label htmlFor="id_name">Name</label>
              <input
                id="id_name"
                type="text"
                placeholder="Context Name"
                maxLength={100}
                value={name}
                aria-invalid={!!errors.fields.name}
                onChange={(event) => setName(event.target.value)}
              />
              <FieldErrors errors={errors.fields.name} />
            </div>
            <div className="field">
              <label htmlFor="id_description">Description</label>
              <textarea
                id="id_description"
                rows={3}
                placeholder="Description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
              <FieldErrors errors={errors.fields.description} />
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn--primary" disabled={create.isPending}>
                <Icon icon={faPlus} /> Create context
              </button>
            </div>
          </section>
        </form>
      </div>
    </>
  );
}
