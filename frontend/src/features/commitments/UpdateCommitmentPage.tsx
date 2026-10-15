import { useParams } from "react-router";
import { faArrowLeft } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { ApiError } from "@/api/errors";
import { DeskHead } from "@/features/contexts-tags/ui";
import { useCommitment } from "./api";
import { CommitmentForm } from "./CommitmentForm";

/* Edit a commitment. The record is read fresh (with its version) so the
   write can carry If-Match; the form notices if it changes underneath. */
export default function UpdateCommitmentPage() {
  const id = Number(useParams().commitmentId);
  const query = useCommitment(id);

  if (query.isPending) {
    return (
      <>
        <DeskHead title="Commitment" />
        <section className="slab">
          <Skeleton lines={6} />
        </section>
      </>
    );
  }
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <>
        <DeskHead title="Commitment not found" />
        <section className="slab slab-pad">
          <Empty>That commitment no longer exists.</Empty>
          <AppLink className="btn btn--ghost" href={urls.home()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
        </section>
      </>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return <CommitmentForm mode="edit" commitment={query.data} />;
}
