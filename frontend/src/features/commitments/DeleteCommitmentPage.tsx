import { useNavigate, useParams } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { ApiError, errorMessage } from "@/api/errors";
import { DeskHead } from "@/features/contexts-tags/ui";
import { useCommitment, useDeleteCommitment } from "./api";
import { dayMonthYear, redirectFor, signed } from "./display";
import { aggregationLabel } from "./scope";
import { measureLabel, periodLabel } from "./formModel";

/* "Delete commitment?" confirmation (templates/core/delete_commitment.html). */
export default function DeleteCommitmentPage() {
  const id = Number(useParams().commitmentId);
  const navigate = useNavigate();
  const toast = useToast();
  const remove = useDeleteCommitment(id);
  /* Once deleted, stop reading it: the refetch after invalidation would 404. */
  const query = useCommitment(id, !remove.isSuccess);

  if (query.isPending) {
    return (
      <>
        <DeskHead title="Delete commitment?" />
        <section className="slab">
          <Skeleton lines={4} />
        </section>
      </>
    );
  }
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <>
        <DeskHead title="Delete commitment?" />
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

  const c = query.data;
  const time = c.commitment_type === "time";
  const confirm = () =>
    remove.mutate(c.version, {
      onSuccess: () => {
        toast.success("Commitment deleted successfully");
        navigate(redirectFor(c));
      },
    });

  return (
    <>
      <DeskHead title="Delete commitment?" />
      <section className="slab slab-pad" id={`commitment-${c.id}`}>
        <div className="commit-head">
          <span className="commit-target text-red">{c.target.name}</span>
          <span className="commit-kind">({aggregationLabel(c.aggregation_type)})</span>
          {!c.active ? <span className="badge-paused">paused</span> : null}
          <span className="commit-period">{periodLabel(c.period)}</span>
        </div>

        <div className="meta-list u-mt-4">
          <div className="meta-row">
            <span className="meta-label">Target</span>
            <span className="meta-value text-green">
              {c.target_value}
              {time ? "m" : " sessions"}
            </span>
          </div>
          <div className="meta-row">
            <span className="meta-label">Counts</span>
            <span className="meta-value">{measureLabel(c.commitment_type)}</span>
          </div>
          <div className="meta-row">
            <span className="meta-label">Bank balance</span>
            <span className={`meta-value ${c.balance >= 0 ? "text-green" : "text-red"}`}>{signed(c.balance)}</span>
          </div>
          <div className="meta-row">
            <span className="meta-label">Tracking since</span>
            <span className="meta-value text-cyan">{dayMonthYear(c.ledger_start_at)}</span>
          </div>
        </div>
      </section>

      <p className="confirm-warn">
        <Icon icon={faExclamationTriangle} /> This deletes the commitment and its banking history. Your sessions are untouched, but the
        streak and balance are gone for good.
      </p>

      {remove.isError ? (
        <p className="confirm-warn" role="alert">
          {remove.error instanceof ApiError && remove.error.code === "version_conflict"
            ? "This commitment changed somewhere else. Reload the page to see the latest version, then delete it."
            : errorMessage(remove.error)}
        </p>
      ) : null}

      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={urls.home()}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
        <button className="btn btn--stop btn--spacer" type="button" id="delete-commitment" onClick={confirm} disabled={remove.isPending}>
          <Icon icon={faTrash} /> Delete commitment
        </button>
      </div>
    </>
  );
}
