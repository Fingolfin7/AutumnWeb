import { useMemo, useState, type FormEvent } from "react";
import { faFileExport } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { OptionPicker } from "@/components/OptionPicker";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { ApiError, errorMessage, toApiError } from "@/api/errors";
import { redirectToLogin } from "@/api/client";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { saveBlob } from "./download";
import {
  buildExportQuery,
  EMPTY_EXPORT_FORM,
  exportFilename,
  formatExport,
  orderContexts,
  projectsInScope,
  validateExport,
  type ExportForm,
} from "./exportQuery";
import "./import.css";

/* GET /api/v2/export/, saved as a file. */
async function fetchExport(form: ExportForm): Promise<Blob> {
  const query = buildExportQuery(form).toString();
  let response: Response;
  try {
    response = await fetch(`/api/v2/export/${query ? `?${query}` : ""}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
    });
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (response.status === 401) redirectToLogin();
  const text = await response.text();
  if (!response.ok) {
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      body = undefined;
    }
    throw toApiError(response.status, body);
  }
  return new Blob([formatExport(text, form.compress)], { type: "application/json" });
}

/* Export (core/templates/core/export.html + ExportJSONForm). */
export default function ExportPage() {
  const toast = useToast();
  const contexts = useContexts();
  const tags = useTags();
  const projects = useAllProjects();
  const [form, setForm] = useState<ExportForm>(EMPTY_EXPORT_FORM);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const patch = (changes: Partial<ExportForm>) => setForm((current) => ({ ...current, ...changes }));

  const allProjects = projects.data ?? [];
  const offered = useMemo(
    () => projectsInScope(allProjects, form.context, form.tags, form.projects),
    [allProjects, form.context, form.tags, form.projects],
  );
  const orderedContexts = useMemo(() => orderContexts(contexts.data ?? []), [contexts.data]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const invalid = validateExport(form);
    if (Object.keys(invalid).length) {
      setErrors(Object.fromEntries(Object.entries(invalid).map(([field, message]) => [field, [message]])));
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const blob = await fetchExport(form);
      const filename = exportFilename(form);
      saveBlob(blob, filename);
      toast.success(`Exported ${filename}.`);
    } catch (error) {
      const found: Record<string, string[]> = {};
      const details = error instanceof ApiError ? error.details : undefined;
      if (details && typeof details === "object") {
        for (const [field, value] of Object.entries(details as Record<string, unknown>)) {
          found[field] = Array.isArray(value) ? value.map(String) : [String(value)];
        }
      }
      setErrors(found);
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const fieldErrors = (...names: string[]) =>
    names
      .flatMap((name) => errors[name] ?? [])
      .map((line) => (
        <p key={line} className="io-field-error" role="alert">
          {line}
        </p>
      ));

  return (
    <div className="export-page">
      <div className="desk-head">
        <div>
          <h1 className="page-title">Export</h1>
        </div>
      </div>

      <section id="export_options">
        <form className="fields" onSubmit={onSubmit} noValidate>
          <div className="split">
            <div>
              <section className="slab slab-pad">
                <div className="two-up">
                  <div className="field">
                    <label htmlFor="export-start-date">Start date</label>
                    <input
                      id="export-start-date"
                      type="date"
                      value={form.startDate}
                      onChange={(event) => patch({ startDate: event.target.value })}
                    />
                    {fieldErrors("start_date")}
                  </div>
                  <div className="field">
                    <label htmlFor="export-end-date">End date</label>
                    <input
                      id="export-end-date"
                      type="date"
                      value={form.endDate}
                      onChange={(event) => patch({ endDate: event.target.value })}
                    />
                    {fieldErrors("end_date")}
                  </div>
                </div>

                <div className="field">
                  <label htmlFor="export-context-filter">Context</label>
                  <select
                    id="export-context-filter"
                    value={form.context}
                    onChange={(event) => patch({ context: event.target.value })}
                  >
                    <option value="">All Contexts</option>
                    {orderedContexts.map((context) => (
                      <option key={context.id} value={context.id}>
                        {context.name}
                      </option>
                    ))}
                  </select>
                  {fieldErrors("context_ids")}
                </div>

                {tags.data?.length ? (
                  <>
                    <OptionPicker
                      label="Tags"
                      options={tags.data.map((tag) => ({ id: tag.id, label: tag.name, color: tag.color }))}
                      selected={form.tags}
                      onChange={(ids) => patch({ tags: ids })}
                      emptyText="No tags match that search."
                    />
                    {fieldErrors("tag_ids")}
                  </>
                ) : (
                  <div className="field">
                    <span className="field-label">Tags</span>
                    <p className="empty">
                      {tags.isPending ? (
                        "Loading tags..."
                      ) : (
                        <>
                          No tags are available. <AppLink href={urls.tags()}>Create one</AppLink> to filter exports by
                          label.
                        </>
                      )}
                    </p>
                  </div>
                )}

                <div id="search_projects" className="field">
                  <label htmlFor="project-search">Project name</label>
                  <input
                    id="project-search"
                    type="text"
                    list="export-project-names"
                    autoComplete="off"
                    placeholder="Projects (leave blank to export all)"
                    value={form.projectName}
                    onChange={(event) => patch({ projectName: event.target.value })}
                  />
                  <datalist id="export-project-names">
                    {allProjects.map((project) => (
                      <option key={project.id} value={project.name} />
                    ))}
                  </datalist>
                  {fieldErrors("project_name")}
                </div>

                {allProjects.length ? (
                  <>
                    <OptionPicker
                      label="Projects"
                      options={offered.map((project) => ({ id: project.id, label: project.name }))}
                      selected={form.projects}
                      onChange={(ids) => patch({ projects: ids })}
                      searchPlaceholder="Search projects..."
                      emptyText="No projects match that search."
                      mode={form.projectMode}
                      onModeChange={(projectMode) => patch({ projectMode })}
                    />
                    {fieldErrors("project_ids", "exclude_project_ids")}
                  </>
                ) : (
                  <div className="field">
                    <span className="field-label">Projects</span>
                    <p className="empty">
                      {projects.isPending ? (
                        "Loading projects..."
                      ) : (
                        <>
                          No projects are available. <AppLink href={urls.createProject()}>Create one</AppLink> before
                          exporting project data.
                        </>
                      )}
                    </p>
                  </div>
                )}
              </section>
            </div>

            <section className="slab slab-pad">
              <div className="field">
                <label htmlFor="export-output-file">Output file</label>
                <input
                  id="export-output-file"
                  type="text"
                  placeholder="Filename (leave blank to use default)"
                  value={form.outputFile}
                  onChange={(event) => patch({ outputFile: event.target.value })}
                />
              </div>

              <div className="check-row">
                <input
                  id="export-legacy"
                  type="checkbox"
                  checked={form.legacy}
                  onChange={(event) => patch({ legacy: event.target.checked })}
                />
                <label htmlFor="export-legacy">Legacy format 1</label>
              </div>

              <div className="check-row">
                <input
                  id="export-autumn"
                  type="checkbox"
                  checked={form.autumnCompatible}
                  onChange={(event) => patch({ autumnCompatible: event.target.checked })}
                />
                <label htmlFor="export-autumn">Autumn CLI compatible</label>
              </div>
              {form.autumnCompatible && !form.legacy ? (
                <small className="muted">Applies to the legacy format only.</small>
              ) : null}

              <div className="check-row">
                <input
                  id="export-compress"
                  type="checkbox"
                  checked={form.compress}
                  onChange={(event) => patch({ compress: event.target.checked })}
                />
                <label htmlFor="export-compress">Compress</label>
              </div>

              <div className="form-actions">
                <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={busy}>
                  <Icon icon={faFileExport} /> {busy ? "Exporting..." : "Export"}
                </button>
              </div>
            </section>
          </div>
        </form>
      </section>
    </div>
  );
}
