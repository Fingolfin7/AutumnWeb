import { useParams, useNavigate } from "react-router";
import { faArrowLeft, faExclamationTriangle, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { useDeleteTag, useTagById } from "./api";
import { DeskHead, tagStyle } from "./ui";

/* "Delete tag?" confirmation (templates/core/delete_tag.html). */
export default function DeleteTagPage() {
  const id = Number(useParams().tagId);
  const navigate = useNavigate();
  const toast = useToast();
  const { query, item, missing } = useTagById(id);
  const remove = useDeleteTag();

  if (query.isPending) {
    return (
      <>
        <DeskHead title="Delete tag?" />
        <section className="slab">
          <Skeleton lines={3} />
        </section>
      </>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (missing || !item) {
    return (
      <>
        <DeskHead title="Delete tag?" />
        <section className="slab slab-pad">
          <Empty>That tag no longer exists.</Empty>
          <AppLink className="btn btn--ghost" href={urls.tags()}>
            <Icon icon={faArrowLeft} /> Back
          </AppLink>
        </section>
      </>
    );
  }

  const confirm = () =>
    remove.mutate(item.id, {
      onSuccess: () => {
        toast.success("Tag deleted successfully");
        navigate(urls.tags());
      },
    });

  return (
    <>
      <DeskHead title="Delete tag?" />
      <section className="slab slab-pad" id={`tag-${item.id}`}>
        <p className="confirm-lede">
          <span className="tag-chip" style={tagStyle(item.color)}>
            {item.name}
          </span>
        </p>
        {item.color ? (
          <p className="muted">
            Colour:{" "}
            <span className="tag-chip" style={tagStyle(item.color)}>
              {item.color}
            </span>
          </p>
        ) : null}
        <p className="muted u-mt-4">
          Used by <span className="mono tnum">{item.project_count}</span> {item.project_count === 1 ? "project" : "projects"}.
        </p>
      </section>

      <p className="confirm-warn">
        <Icon icon={faExclamationTriangle} /> Projects using this tag will lose the association. This cannot be undone.
      </p>

      {remove.isError ? (
        <p className="confirm-warn" role="alert">
          {errorMessage(remove.error)}
        </p>
      ) : null}

      <div className="form-actions">
        <AppLink className="btn btn--ghost" href={urls.tags()}>
          <Icon icon={faArrowLeft} /> Back
        </AppLink>
        <button type="button" className="btn btn--stop btn--spacer" onClick={confirm} disabled={remove.isPending}>
          <Icon icon={faTrash} /> Delete tag
        </button>
      </div>
    </>
  );
}
