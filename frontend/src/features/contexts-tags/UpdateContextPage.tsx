import { useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faCheckCircle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useAllProjects } from "@/api/meta";
import { RelatedCommitments } from "@/features/commitments/RelatedCommitments";
import type { Context } from "@/api/types";
import { useContextById, useUpdateContext } from "./api";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "./formErrors";
import { StatsList } from "./StatsList";
import { summarizeProjects, validateName } from "./stats";
import { DeskHead, FieldErrors, FormLevelErrors } from "./ui";

/* Edit a context (templates/core/update_context.html). */
export default function UpdateContextPage() {
  const id = Number(useParams().contextId);
  const { query, item, missing } = useContextById(id);

  if (query.isPending || (!item && !missing && !query.isError)) {
    return (
      <>
        <DeskHead title="Context" />
        <section className="slab">
          <Skeleton lines={4} />
        </section>
      </>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (missing || !item) {
    return (
      <>
        <DeskHead title="Context not found" />
        <section className="slab slab-pad">
          <Empty>That context no longer exists.</Empty>
          <AppLink className="btn btn--ghost" href={urls.contexts()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
        </section>
      </>
    );
  }
  return <ContextEditor item={item} all={query.data ?? []} />;
}

/* Mounted once the record exists, so the fields start from its values. */
function ContextEditor({ item, all }: { item: Context; all: Context[] }) {
  const navigate = useNavigate();
  const toast = useToast();
  const projects = useAllProjects();
  const update = useUpdateContext(item.id);
  const [name, setName] = useState(item.name);
  const [description, setDescription] = useState(item.description ?? "");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const summary = useMemo(
    () => summarizeProjects((projects.data ?? []).filter((project) => project.context?.id === item.id)),
    [projects.data, item.id],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problem = validateName(name, "context", all, item.id);
    if (problem) {
      setErrors({ fields: { name: [problem] }, general: [] });
      return;
    }
    setErrors(NO_ERRORS);
    update.mutate(
      { name: name.trim(), description: description.trim() || null },
      {
        onSuccess: () => {
          toast.success("Context updated successfully");
          navigate(urls.contexts());
        },
        onError: (error) => setErrors(parseFormErrors(error, { conflictField: "name" })),
      },
    );
  };

  return (
    <>
      <DeskHead title={item.name} />
      <form className="fields" onSubmit={submit} noValidate>
        <FormLevelErrors errors={errors.general} />
        <div className="split">
          <section className="slab slab-pad">
            <div className="field">
              <label htmlFor="id_name">Name</label>
              <input
                id="id_name"
                type="text"
                maxLength={100}
                value={name}
                aria-invalid={!!errors.fields.name}
onChange={(event) => setName(event.target.value)}
              />
              <FieldErrors errors={errors.fields.name} />
            </div>
            <div className="field">
              <label htmlFor="id_description">Description</label>
              <textarea id="id_description" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
              <FieldErrors errors={errors.fields.description} />
            </div>
            <div className="form-actions">
              <AppLink className="btn btn--ghost" href={urls.contexts()}>
                <Icon icon={faArrowLeft} /> Back
              </AppLink>
              <button type="submit" className="btn btn--primary" disabled={update.isPending}>
                <Icon icon={faCheckCircle} /> Save changes
              </button>
              <AppLink className="btn btn--ghost btn--spacer" href={`/delete_context/${item.id}/`}>
                <Icon icon={faTrash} /> Delete context
              </AppLink>
            </div>
          </section>

          <section className="slab slab-pad">
            <StatsList summary={summary} />
          </section>
        </div>
      </form>

      <RelatedCommitments kind="context" id={item.id} />
    </>
  );
}
