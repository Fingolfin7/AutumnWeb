import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { faArrowLeft, faCodeBranch } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { useAllProjects } from "@/api/meta";
import { formatDurationWords, pluralize } from "@/lib/format";
import { failure, useMergeProjects } from "./api";
import { splitErrors } from "./forms";
import { FieldError, FormErrors, LoadState, PageHead } from "./Parts";

const FIELDS = ["source_ids", "new_name"];

export default function MergeProjectsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const projects = useAllProjects();
  const merge = useMergeProjects();
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [newName, setNewName] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);
  const errors = splitErrors(merge.error, FIELDS, "new_name");
  const list = projects.data ?? [];
  const a = list.find((project) => String(project.id) === first);
  const b = list.find((project) => String(project.id) === second);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!a || !b) return;
    if (a.id === b.id) {
      setClientError("Cannot merge a project with itself.");
      return;
    }
    setClientError(null);
    merge.mutate(
      { source_ids: [a.id, b.id], new_name: newName.trim() },
      {
        onSuccess: (merged) => {
          toast.success(`Successfully merged '${a.name}' and '${b.name}' into '${merged.name}'`);
          navigate(urls.projects());
        },
        onError: (error) => {
          if (splitErrors(error, FIELDS, "new_name").general.length) toast.error(failure("merge the projects", error));
        },
      },
    );
  };

  return (
    <>
      <PageHead title="Merge projects" />
      <LoadState query={projects}>
        <form className="fields" onSubmit={onSubmit}>
          <section className="slab slab-pad">
            <p className="focus-lede">Every session, subproject and tag from both projects ends up under one name. The originals are removed.</p>

            {clientError || errors.general.length ? (
              <div className="u-mt-4">
                <FormErrors errors={{ fields: {}, general: clientError ? [clientError] : errors.general }} />
              </div>
            ) : null}

            <div className="two-up u-mt-4">
              <div className="field">
                <label htmlFor="project1">First project</label>
                <select id="project1" required value={first} onChange={(e) => setFirst(e.target.value)}>
                  <option value="">Select first project</option>
                  {list.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label htmlFor="project2">Second project</label>
                <select id="project2" required value={second} onChange={(e) => setSecond(e.target.value)}>
                  <option value="">Select second project</option>
                  {list.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="new_project_name">Name for the merged project</label>
              <input
                id="new_project_name"
                type="text"
                placeholder="Enter name for merged project"
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
            <AppLink className="btn btn--ghost" href={urls.projects()}>
              <Icon icon={faArrowLeft} /> Back
            </AppLink>
            <button className="btn btn--primary btn--spacer" type="submit" disabled={merge.isPending}>
              <Icon icon={faCodeBranch} /> Merge projects
            </button>
          </div>
        </form>
      </LoadState>
    </>
  );
}
