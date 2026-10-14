import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faCodeBranch } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useSubprojects } from "@/api/meta";
import { formatDurationWords, pluralize } from "@/lib/format";
import { failure, useMergeSubprojects, useProject } from "./api";
import { splitErrors } from "./forms";
import { FieldError, FormErrors, LoadState, PageHead } from "./Parts";

const FIELDS = ["source_ids", "new_name"];

export default function MergeSubprojectsPage() {
  const projectId = Number(useParams().projectId);
  const project = useProject(projectId);
  return <LoadState query={project}>{project.data ? <MergeSubprojectsForm projectId={projectId} projectName={project.data.name} /> : null}</LoadState>;
}

function MergeSubprojectsForm({ projectId, projectName }: { projectId: number; projectName: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const subprojects = useSubprojects(projectId);
  const merge = useMergeSubprojects();
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [newName, setNewName] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);
  const errors = splitErrors(merge.error, FIELDS, "new_name");
  const list = subprojects.data ?? [];
  const a = list.find((sub) => String(sub.id) === first);
  const b = list.find((sub) => String(sub.id) === second);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!a || !b) return;
    if (a.id === b.id) {
      setClientError("Cannot merge a subproject with itself.");
      return;
    }
    setClientError(null);
    merge.mutate(
      { project_id: projectId, source_ids: [a.id, b.id], new_name: newName.trim() },
      {
        onSuccess: (merged) => {
          toast.success(`Successfully merged '${a.name}' and '${b.name}' into '${merged.name}'`);
          navigate(urls.updateProject(projectId));
        },
        onError: (error) => {
          if (splitErrors(error, FIELDS, "new_name").general.length) toast.error(failure("merge the subprojects", error));
        },
      },
    );
  };

  const options = (
    <>
      {list.map((sub) => (
        <option key={sub.id} value={sub.id}>
          {sub.name}
        </option>
      ))}
    </>
  );

  return (
    <>
      <PageHead
        eyebrow={
          <AppLink className="text-red" href={urls.updateProject(projectId)}>
            {projectName}
          </AppLink>
        }
        title="Merge subprojects"
      />
      <LoadState query={subprojects}>
        <form className="fields" onSubmit={onSubmit}>
          <section className="slab slab-pad">
            <p className="focus-lede">Every session attached to either subproject ends up under one name. The originals are removed.</p>

            {clientError || errors.general.length ? (
              <div className="u-mt-4">
                <FormErrors errors={{ fields: {}, general: clientError ? [clientError] : errors.general }} />
              </div>
            ) : null}

            <div className="two-up u-mt-4">
              <div className="field">
                <label htmlFor="subproject1">First subproject</label>
                <select id="subproject1" required value={first} onChange={(e) => setFirst(e.target.value)}>
                  <option value="">Select first subproject</option>
                  {options}
                </select>
              </div>

              <div className="field">
                <label htmlFor="subproject2">Second subproject</label>
                <select id="subproject2" required value={second} onChange={(e) => setSecond(e.target.value)}>
                  <option value="">Select second subproject</option>
                  {options}
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="new_subproject_name">Name for the merged subproject</label>
              <input
                id="new_subproject_name"
                type="text"
                placeholder="Enter name for merged subproject"
                maxLength={255}
                required
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <FieldError message={errors.fields.new_name} />
              {a && b && a.id !== b.id ? (
                <p className="muted u-mt-4">
                  Together: {formatDurationWords(a.total_minutes + b.total_minutes)} across {pluralize(a.session_count + b.session_count, "session")}.
                </p>
              ) : null}
            </div>
          </section>

          <div className="form-actions">
            <AppLink className="btn btn--ghost" href={urls.updateProject(projectId)}>
              <Icon icon={faArrowLeft} /> Back
            </AppLink>
            <button className="btn btn--primary btn--spacer" type="submit" disabled={merge.isPending}>
              <Icon icon={faCodeBranch} /> Merge subprojects
            </button>
          </div>
        </form>
      </LoadState>
    </>
  );
}
