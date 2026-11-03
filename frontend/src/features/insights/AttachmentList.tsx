import { faExclamationTriangle, faFileAlt, faFilePdf, faFileWord, faTimes } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { formatSize, type AttachmentKind, type AttachmentView, type Draft } from "./attachments";

function fileIcon(kind: AttachmentKind, name: string) {
  if (kind === "pdf") return faFilePdf;
  if (/\.docx$/i.test(name)) return faFileWord;
  return faFileAlt;
}

function typeLabel(kind: AttachmentKind, name: string): string {
  if (kind === "pdf") return "PDF";
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1];
  return ext ? ext.toUpperCase() : "File";
}

/* The files waiting to go with the next question. */
export function AttachmentTray({ drafts, onRemove }: { drafts: Draft[]; onRemove: (key: string) => void }) {
  if (!drafts.length) return null;
  return (
    <ul className="attach-tray" aria-label="Attached files">
      {drafts.map((draft) => {
        const status =
          draft.status === "uploading" ? `Uploading ${Math.round(draft.progress * 100)}%` : draft.status === "error" ? draft.error ?? "Upload failed." : `${typeLabel(draft.kind, draft.name)} · ${formatSize(draft.size)}`;
        const image = draft.kind === "image" && draft.preview;
        return (
          <li
            key={draft.key}
            className={`attach-chip${image ? " attach-chip--image" : ""} is-${draft.status}`}
            title={`${draft.name}\n${status}`}
          >
            {image ? (
              <img className="attach-thumb" src={draft.preview!} alt="" />
            ) : (
              <span className="attach-icon" aria-hidden="true">
                <Icon icon={draft.status === "error" ? faExclamationTriangle : fileIcon(draft.kind, draft.name)} />
              </span>
            )}
            {image ? (
              draft.status === "error" ? (
                <span className="attach-thumb-alert" aria-hidden="true">
                  <Icon icon={faExclamationTriangle} />
                </span>
              ) : null
            ) : (
              <span className="attach-text">
                <span className="attach-name">{draft.name}</span>
                <span className="attach-meta" role={draft.status === "error" ? "alert" : undefined}>
                  {status}
                </span>
              </span>
            )}
            {image && draft.status === "error" ? (
              <span className="sr-only" role="alert">
                {draft.name}: {status}
              </span>
            ) : null}
            {draft.status === "uploading" ? (
              <span className="attach-progress" aria-hidden="true">
                <span style={{ transform: `scaleX(${Math.max(draft.progress, 0.04)})` }} />
              </span>
            ) : null}
            <button type="button" className="attach-remove" onClick={() => onRemove(draft.key)} aria-label={`Remove ${draft.name}`} title="Remove">
              <Icon icon={faTimes} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* A sent question's files: screenshots as thumbnails, documents as chips. */
export function MessageAttachments({ items }: { items: AttachmentView[] }) {
  if (!items.length) return null;
  const images = items.filter((a) => a.kind === "image");
  const files = items.filter((a) => a.kind !== "image");
  return (
    <div className="msg-attachments">
      {images.length ? (
        <div className={`msg-images${images.length === 1 ? " is-single" : ""}`}>
          {images.map((image) => (
            <a key={image.url} href={image.url} target="_blank" rel="noopener noreferrer" className="msg-image" title={`${image.name} (opens full size)`}>
              <img src={image.url} alt={image.name} loading="lazy" />
            </a>
          ))}
        </div>
      ) : null}
      {files.length ? (
        <div className="msg-files">
          {files.map((file) => (
            <a key={file.url} href={file.url} className="attach-chip attach-chip--link" title={`Download ${file.name}`}>
              <span className="attach-icon" aria-hidden="true">
                <Icon icon={fileIcon(file.kind, file.name)} />
              </span>
              <span className="attach-text">
                <span className="attach-name">{file.name}</span>
                <span className="attach-meta">
                  {typeLabel(file.kind, file.name)} · {formatSize(file.size)}
                </span>
              </span>
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}
