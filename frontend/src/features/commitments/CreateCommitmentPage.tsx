import { useParams, useSearchParams } from "react-router";
import { faArrowLeft } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { DeskHead } from "@/features/contexts-tags/ui";
import { useAllSubprojects } from "./api";
import { CommitmentForm } from "./CommitmentForm";
import type { Aggregation } from "./scope";

const KINDS: Aggregation[] = ["context", "tag", "project", "subproject"];

/* New commitment. /create_commitment/<projectId>/ starts on that project;
   ?aggregation_type=&target_id= (used by the context and tag pages) starts on
   that item. An id that is not the user's is ignored, like the old view did. */
export default function CreateCommitmentPage() {
  const projectId = Number(useParams().projectId) || null;
  const [params] = useSearchParams();
  const kindParam = params.get("aggregation_type") ?? "";
  const targetParam = Number(params.get("target_id")) || null;
  const kind: Aggregation | null = projectId ? "project" : KINDS.includes(kindParam as Aggregation) ? (kindParam as Aggregation) : null;
  const targetId = projectId ?? targetParam;

  const projects = useAllProjects();
  const contexts = useContexts();
  const tags = useTags();
  const subs = useAllSubprojects(kind === "subproject");

  const wanted =
    kind === "project" ? projects : kind === "context" ? contexts : kind === "tag" ? tags : kind === "subproject" ? subs : null;
  const loading = projects.isPending || (wanted !== null && wanted.isPending);
  const error = projects.error ?? (wanted && "error" in wanted ? wanted.error : null);

  if (error) return <ErrorState error={error} />;
  if (loading) {
    return (
      <>
        <DeskHead title="New commitment" />
        <section className="slab">
          <Skeleton lines={5} />
        </section>
      </>
    );
  }

  let exists = false;
  if (kind && targetId) {
    exists =
      kind === "project"
        ? !!projects.data?.some((p) => p.id === targetId)
        : kind === "context"
          ? !!contexts.data?.some((c) => c.id === targetId)
          : kind === "tag"
            ? !!tags.data?.some((t) => t.id === targetId)
            : subs.subprojects.some((s) => s.id === targetId);
  }

  if (projectId && !exists) {
    return (
      <>
        <DeskHead title="New commitment" />
        <section className="slab slab-pad">
          <Empty>That project no longer exists.</Empty>
          <AppLink className="btn btn--ghost" href={urls.projects()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
        </section>
      </>
    );
  }

  return <CommitmentForm mode="create" prefill={exists && kind && targetId ? { aggregation: kind, targetId } : undefined} />;
}
