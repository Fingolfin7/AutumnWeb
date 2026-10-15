import { useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { faArrowLeft, faCheckCircle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { useToast } from "@/app/toasts";
import { useAllProjects, useContexts } from "@/api/meta";
import { RelatedCommitments } from "@/features/commitments/RelatedCommitments";
import type { Tag } from "@/api/types";
import { useTagById, useUpdateTag } from "./api";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "./formErrors";
import { StatsList } from "./StatsList";
import { summarizeProjects, validateName } from "./stats";
import { DeskHead, FieldErrors, FormLevelErrors, tagStyle } from "./ui";

/* Edit a tag (templates/core/update_tag.html). The sidebar's context select
   narrows the project stats, and lives in ?context= like the old page. */
export default function UpdateTagPage() {
  const id = Number(useParams().tagId);
  const { query, item, missing } = useTagById(id);

  if (query.isPending || (!item && !missing && !query.isError)) {
    return (
      <>
        <DeskHead title="Tag" />
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
        <DeskHead title="Tag not found" />
        <section className="slab slab-pad">
          <Empty>That tag no longer exists.</Empty>
          <AppLink className="btn btn--ghost" href={urls.tags()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
        </section>
      </>
    );
  }
  return <TagEditor item={item} all={query.data ?? []} />;
}

/* Mounted once the record exists, so the fields start from its values. */
function TagEditor({ item, all }: { item: Tag; all: Tag[] }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const { contextId } = useActiveContext();
  const projects = useAllProjects();
  const contexts = useContexts();
  const update = useUpdateTag(item.id);
  const id = item.id;
  const [name, setName] = useState(item.name);
  const [color, setColor] = useState(item.color ?? "");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  /* Stats follow the header's context unless this page picks one; the old
     page did that too but always showed "All" in the select. */
  const scope = params.get("context") ?? (contextId === null ? "all" : String(contextId));
  const summary = useMemo(
    () =>
      summarizeProjects(
        (projects.data ?? []).filter(
          (project) => project.tags.some((tag) => tag.id === id) && (scope === "all" || String(project.context?.id) === scope),
        ),
      ),
    [projects.data, id, scope],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problem = validateName(name, "tag", all, item.id);
    if (problem) {
      setErrors({ fields: { name: [problem] }, general: [] });
      return;
    }
    setErrors(NO_ERRORS);
    update.mutate(
      { name: name.trim(), color: color.trim() || null },
      {
        onSuccess: () => {
          toast.success("Tag updated successfully");
          navigate(urls.tags());
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
              <label htmlFor="id_color">Color</label>
              <input
                id="id_color"
                type="text"
                placeholder="Optional color (e.g. #ff0000 or label)"
                maxLength={20}
                value={color}
                onChange={(event) => setColor(event.target.value)}
              />
              <FieldErrors errors={errors.fields.color} />
              {name.trim() ? (
                <p className="u-mt-4">
                  <span className="tag-chip" style={tagStyle(color.trim())}>
                    {name.trim()}
                  </span>
                </p>
              ) : null}
            </div>
            <div className="form-actions">
              <AppLink className="btn btn--ghost" href={urls.tags()}>
                <Icon icon={faArrowLeft} /> Back
              </AppLink>
              <button type="submit" className="btn btn--primary" disabled={update.isPending}>
                <Icon icon={faCheckCircle} /> Save changes
              </button>
              <AppLink className="btn btn--ghost btn--spacer" href={`/delete_tag/${item.id}/`}>
                <Icon icon={faTrash} /> Delete tag
              </AppLink>
            </div>
          </section>

          <section className="slab slab-pad">
            <div className="field">
              <label htmlFor="tag-context-select">Context</label>
              <select
                id="tag-context-select"
                value={scope}
                onChange={(event) => setParams(event.target.value ? { context: event.target.value } : {}, { replace: true })}
              >
                <option value="all">All</option>
                {(contexts.data ?? []).map((ctx) => (
                  <option key={ctx.id} value={String(ctx.id)}>
                    {ctx.name}
                  </option>
                ))}
              </select>
            </div>
            <StatsList summary={summary} />
          </section>
        </div>
      </form>

      <RelatedCommitments kind="tag" id={item.id} />
    </>
  );
}
