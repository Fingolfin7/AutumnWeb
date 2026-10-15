import type { ReactNode } from "react";
import { faExclamationCircle, faExclamationTriangle } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { OptionPicker } from "@/components/OptionPicker";
import { Skeleton, ErrorState } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useContexts, useTags } from "@/api/meta";
import type { ProjectStatus } from "@/api/types";

import type { SplitErrors } from "./forms";
import { STATUS_ORDER, type ProjectValues } from "./logic";

/* The page heading block every project form page opens with
   (.desk-head: optional eyebrow link above the title). */
export function PageHead({ eyebrow, title, titleClass }: { eyebrow?: ReactNode; title: ReactNode; titleClass?: string }) {
  return (
    <div className="desk-head">
      <div>
        {eyebrow ? <p className="page-eyebrow">{eyebrow}</p> : null}
        <h1 className={`page-title${titleClass ? " " + titleClass : ""}`}>{title}</h1>
      </div>
    </div>
  );
}

/** Django's {{ field.errors }}. */
export function FieldError({ message }: { message?: string }) {
  return message ? (
    <ul className="errorlist" role="alert">
      <li>{message}</li>
    </ul>
  ) : null;
}

/** Errors that belong to no single field (Django's non_field_errors). */
export function FormErrors({ errors }: { errors: SplitErrors }) {
  if (!errors.general.length) return null;
  return (
    <div className="msg msg--error" role="alert" style={{ marginBottom: "var(--s4)" }}>
      <Icon icon={faExclamationCircle} className="msg-icon" />
      <span>{errors.general.join(" ")}</span>
    </div>
  );
}

/* The 409 version_conflict notice, worded like the session edit page's: the
   record was changed (another tab, the CLI, an assistant) after this page
   opened it. `outcome` says what did not happen; the buttons are for edit
   pages ("Save mine anyway" only when the server named the current version). */
export function ConflictBanner({
  noun,
  outcome,
  onLoadLatest,
  onSaveAnyway,
  busy,
}: {
  noun: string;
  outcome?: string;
  onLoadLatest?: () => void;
  onSaveAnyway?: () => void;
  busy?: boolean;
}) {
  return (
    <div className="msg msg--warning" role="alert" style={{ marginBottom: "var(--s4)" }}>
      <Icon icon={faExclamationTriangle} className="msg-icon" />
      <span>
        This {noun} was changed somewhere else (another tab, the CLI or an assistant) after you opened it.
        {outcome ? ` ${outcome}` : ""}
      </span>
      {onLoadLatest ? (
        <button type="button" className="toast-action" onClick={onLoadLatest}>
          Load latest
        </button>
      ) : null}
      {onSaveAnyway ? (
        <button type="button" className="toast-action" disabled={busy} onClick={onSaveAnyway}>
          Save mine anyway
        </button>
      ) : null}
    </div>
  );
}

/** Page-level fallback while a record loads or fails to load. */
export function LoadState({ query, children }: { query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; children: ReactNode }) {
  if (query.isPending) {
    return (
      <section className="slab slab-pad">
        <Skeleton lines={5} />
      </section>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return <>{children}</>;
}

/* Name, (status,) description, context and tags: the fields create and update
   share, in the order both old forms listed them. */
export function ProjectFields({
  values,
  onChange,
  errors,
  showStatus,
}: {
  values: ProjectValues;
  onChange: (next: ProjectValues) => void;
  errors: SplitErrors;
  showStatus?: boolean;
}) {
  const contexts = useContexts();
  const tags = useTags();
  const set = <K extends keyof ProjectValues>(key: K, value: ProjectValues[K]) => onChange({ ...values, [key]: value });
  return (
    <>
      <div className="field">
        <label htmlFor="id_name">Name</label>
        <input id="id_name" type="text" placeholder="Project Name" maxLength={255} required value={values.name} onChange={(e) => set("name", e.target.value)} />
        <FieldError message={errors.fields.name} />
      </div>

      {showStatus ? (
        <div className="field">
          <label htmlFor="id_status">Status</label>
          <select id="id_status" value={values.status} onChange={(e) => set("status", e.target.value as ProjectStatus)}>
            {STATUS_ORDER.map((option) => (
              <option key={option.status} value={option.status}>
                {option.label}
              </option>
            ))}
          </select>
          <FieldError message={errors.fields.status} />
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="id_description">Description</label>
        <textarea id="id_description" placeholder="Description" rows={3} value={values.description} onChange={(e) => set("description", e.target.value)} />
        <FieldError message={errors.fields.description} />
      </div>

      <div className="field">
        <label htmlFor="id_context">Context</label>
        <select id="id_context" value={values.context_id ?? ""} onChange={(e) => set("context_id", e.target.value ? Number(e.target.value) : null)}>
          <option value="">No context</option>
          {(contexts.data ?? []).map((context) => (
            <option key={context.id} value={context.id}>
              {context.name}
            </option>
          ))}
        </select>
        <FieldError message={errors.fields.context_id} />
      </div>

      {tags.data?.length ? (
        <>
          <OptionPicker
            label="Tags"
            options={tags.data.map((tag) => ({ id: tag.id, label: tag.name, color: tag.color }))}
            selected={values.tag_ids}
            onChange={(ids) => set("tag_ids", ids)}
          />
          <FieldError message={errors.fields.tag_ids} />
        </>
      ) : (
        <div className="field">
          <span className="field-label">Tags</span>
          <p className="muted">
            {tags.isPending ? "Loading tags…" : (
              <>
                No tags yet. <AppLink href={urls.tags()}>Create one</AppLink> to group projects.
              </>
            )}
          </p>
        </div>
      )}
    </>
  );
}
