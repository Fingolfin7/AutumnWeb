import { useState, type FormEvent } from "react";
import { faPlus } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useTags } from "@/api/meta";
import { pluralize } from "@/lib/format";
import { useCreateTag } from "./api";
import { NO_ERRORS, parseFormErrors, type FormErrors } from "./formErrors";
import { validateName } from "./stats";
import { DeskHead, FieldErrors, FormLevelErrors, tagStyle } from "./ui";

/* Tags list + create form (templates/core/tags.html). */
export default function TagsPage() {
  const tags = useTags();
  const create = useCreateTag();
  const toast = useToast();
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problem = validateName(name, "tag", tags.data ?? []);
    if (problem) {
      setErrors({ fields: { name: [problem] }, general: [] });
      return;
    }
    setErrors(NO_ERRORS);
    create.mutate(
      { name: name.trim(), color: color.trim() || null },
      {
        onSuccess: () => {
          toast.success("Tag created successfully");
          setName("");
          setColor("");
        },
        onError: (error) => setErrors(parseFormErrors(error, { conflictField: "name" })),
      },
    );
  };

  return (
    <>
      <DeskHead title="Tags" />
      <div className="split">
        <section id="tags-list" className="slab" aria-label="Tags">
          {tags.isPending ? (
            <Skeleton lines={4} />
          ) : tags.isError ? (
            <ErrorState error={tags.error} onRetry={() => void tags.refetch()} />
          ) : tags.data.length ? (
            <ul className="band-list">
              {tags.data.map((tag) => (
                <li key={tag.id} className="band band--tap u-row u-between u-gap-3">
                  <AppLink className="tag-chip" href={urls.updateTag(tag.id)} style={tagStyle(tag.color)}>
                    {tag.name}
                  </AppLink>
                  <span className="muted mono tnum">{pluralize(tag.project_count, "project")}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>
              No tags yet. <a href="#create-tag">Create one</a> to label related projects.
            </Empty>
          )}
        </section>

        <form className="fields" id="create-tag" onSubmit={submit} noValidate>
          <FormLevelErrors errors={errors.general} />
          <section className="slab slab-pad">
            <div className="field">
              <label htmlFor="id_name">Name</label>
              <input
                id="id_name"
                type="text"
                placeholder="Tag Name"
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
              <button type="submit" className="btn btn--primary" disabled={create.isPending}>
                <Icon icon={faPlus} /> Create tag
              </button>
            </div>
          </section>
        </form>
      </div>
    </>
  );
}
