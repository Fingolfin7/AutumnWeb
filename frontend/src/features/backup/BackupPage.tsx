import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { faDownload, faUndo } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ConfirmDialog } from "@/components/Sheet";
import { FileDrop, Toggle } from "@/components/ui";
import { useToast } from "@/app/toasts";
import { ApiError, errorMessage } from "@/api/errors";
import { pluralize } from "@/lib/format";
import {
  downloadBackup,
  formatBytes,
  inventory,
  previewBackup,
  refreshAfterRestore,
  restoreBackup,
  sectionLabel,
  useBackupSummary,
  type BackupPreview,
} from "./api";
import "./backup.css";

/* Settings > Data > Backup & restore. */
export default function BackupPage() {
  return (
    <div className="backup-page">
      <BackupDownload />
      <BackupRestore />
    </div>
  );
}

function BackupDownload() {
  const toast = useToast();
  const summary = useBackupSummary();
  const [insights, setInsights] = useState(true);
  const [attachments, setAttachments] = useState(false);
  const [busy, setBusy] = useState(false);
  const files = summary.data?.attachment_count ?? 0;

  const download = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const name = await downloadBackup({ insights, attachments: insights && attachments });
      toast.success(`Saved ${name}.`);
    } catch (error) {
      toast.error(`Couldn't make the backup: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="slab slab-pad backup-block" aria-labelledby="backup-download-title">
      <h2 className="backup-title" id="backup-download-title">
        Back up this account
      </h2>
      <p className="backup-lede">
        One ZIP with your contexts, tags, projects, completed sessions, commitments and their history, planned reminders and
        settings, including your profile photo and backdrop.
      </p>
      <div className="backup-options">
        <Toggle
          label="Include Insights chats"
          checked={insights}
          disabled={busy}
          onChange={(event) => setInsights(event.target.checked)}
        />
        <div>
          <Toggle
            label="Include files attached to Insights chats"
            checked={insights && attachments}
            disabled={busy || !insights || (summary.isSuccess && files === 0)}
            aria-describedby="backup-files-hint"
            onChange={(event) => setAttachments(event.target.checked)}
          />
          <p className="backup-hint" id="backup-files-hint">
            {!insights
              ? "Files belong to chats, so they come with the chats."
              : summary.isPending
                ? "Checking your files…"
                : summary.isError
                  ? "Couldn't check your files."
                  : files
                    ? `${pluralize(files, "file")}, ${formatBytes(summary.data!.attachment_bytes)}.`
                    : "No files attached to chats."}
          </p>
        </div>
      </div>
      <p className="backup-hint">
        Never included: your password, API keys and connected apps. Running timers aren't included; stop them first to keep them.
      </p>
      <div className="form-actions">
        <button type="button" className="btn btn--primary" onClick={() => void download()} disabled={busy} aria-busy={busy || undefined}>
          <Icon icon={faDownload} /> {busy ? "Preparing backup…" : "Download backup"}
        </button>
      </div>
    </section>
  );
}

type Problem = { kind: "stale" | "error"; message: string } | null;

function BackupRestore() {
  const client = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [pickerKey, setPickerKey] = useState(0);
  /* The preview is only good for the exact File it was made from. */
  const [preview, setPreview] = useState<{ file: File; data: BackupPreview } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const [done, setDone] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  /* Leaving mid-restore would not stop it, but the result would be lost. */
  useEffect(() => {
    if (!restoring) return;
    const hold = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", hold);
    return () => window.removeEventListener("beforeunload", hold);
  }, [restoring]);

  const runPreview = async (chosen: File) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setPreview(null);
    setProblem(null);
    setDone(null);
    setPreviewing(true);
    try {
      const data = await previewBackup(chosen, controller.signal);
      if (controller.signal.aborted) return;
      setPreview({ file: chosen, data });
    } catch (error) {
      if (controller.signal.aborted) return;
      setProblem({ kind: "error", message: `Couldn't read this backup: ${errorMessage(error)}` });
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setPreviewing(false);
      }
    }
  };

  const choose = (chosen: File | null) => {
    setFile(chosen);
    setDone(null);
    if (chosen) void runPreview(chosen);
    else {
      inFlight.current?.abort();
      inFlight.current = null;
      setPreviewing(false);
      setPreview(null);
      setProblem(null);
    }
  };

  const current = preview && file && preview.file === file ? preview.data : null;
  const counts = current ? inventory(current.counts) : null;
  const destination = current?.destination_account ?? "";

  const restore = async () => {
    setConfirming(false);
    if (!current?.can_restore || !file || restoring) return;
    setRestoring(true);
    setProblem(null);
    try {
      const applied = await restoreBackup(file, current.preview_token);
      const added = applied.restored;
      const message = added
        ? `Restored ${pluralize(added, "record")} into ${applied.destination_account}.`
        : "Everything in this backup is already in this account.";
      await refreshAfterRestore(client);
      setDone(message);
      toast.success(message);
      setFile(null);
      setPreview(null);
      setPickerKey((key) => key + 1);
    } catch (error) {
      const stale =
        error instanceof ApiError &&
        (error.status === 409 || (!!error.details && typeof error.details === "object" && "preview_token" in error.details));
      if (stale) {
        setPreview(null);
        setProblem({ kind: "stale", message: error.message });
      } else {
        setProblem({ kind: "error", message: `Couldn't restore the backup: ${errorMessage(error)}` });
      }
    } finally {
      setRestoring(false);
    }
  };

  const blocked = current && !current.can_restore;
  const nothingToAdd = current && current.can_restore && counts?.total.add === 0;

  return (
    <section className="slab slab-pad backup-block" aria-labelledby="backup-restore-title" aria-busy={previewing || restoring || undefined}>
      <h2 className="backup-title" id="backup-restore-title">
        Restore from a backup
      </h2>
      <p className="backup-lede">Choose an Autumn backup ZIP. You'll see what it would add before anything changes.</p>
      <div className="field">
        <label htmlFor="backup-file" className="sr-only">
          Backup file
        </label>
        <FileDrop
          key={pickerKey}
          id="backup-file"
          accept=".zip,application/zip"
          disabled={restoring}
          hint="Autumn backup (.zip)"
          onFile={choose}
        />
      </div>

      {previewing ? (
        <p className="backup-hint" role="status">
          Reading the backup…
        </p>
      ) : null}

      {problem ? (
        <div className="msg msg--error backup-problem" role="alert">
          <span>{problem.message}</span>
          {file && !previewing ? (
            <button type="button" className="quiet-link" onClick={() => void runPreview(file)} disabled={restoring}>
              Preview again
            </button>
          ) : null}
        </div>
      ) : null}

      {done && !file ? (
        <p className="backup-done" role="status">
          {done}
        </p>
      ) : null}

      {current && counts ? (
        <div className="backup-preview">
          <dl className="backup-facts">
            <div>
              <dt>Restores into</dt>
              <dd>{destination}</dd>
            </div>
            <div>
              <dt>Made from</dt>
              <dd>
                {current.source_account}
                {current.same_account ? <span className="muted"> (this account)</span> : null}
              </dd>
            </div>
            <div>
              <dt>Insights</dt>
              <dd>
                {current.includes_insights ? (current.includes_attachments ? "Chats and their files" : "Chats, without files") : "Not included"}
              </dd>
            </div>
          </dl>
          {!current.same_account ? (
            <p className="backup-notice">
              This backup is from another account. Restoring copies its records into {destination}; {current.source_account} is not
              changed.
            </p>
          ) : null}

          {counts.rows.length ? (
            <table className="backup-inventory">
              <caption className="sr-only">What the backup holds, compared with this account</caption>
              <thead>
                <tr>
                  <th scope="col">In the backup</th>
                  <th scope="col">To add</th>
                  <th scope="col">Already here</th>
                  <th scope="col">Conflicts</th>
                </tr>
              </thead>
              <tbody>
                {counts.rows.map((row) => (
                  <tr key={row.section}>
                    <th scope="row">{row.label}</th>
                    <td>{row.add || "–"}</td>
                    <td>{row.identical || "–"}</td>
                    <td className={row.conflict ? "is-conflict" : undefined}>{row.conflict || "–"}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Total</th>
                  <td>{counts.total.add}</td>
                  <td>{counts.total.identical}</td>
                  <td className={counts.total.conflict ? "is-conflict" : undefined}>{counts.total.conflict}</td>
                </tr>
              </tfoot>
            </table>
          ) : (
            <p className="backup-hint">This backup has no records.</p>
          )}

          {current.conflicts.length ? (
            <div className="backup-conflicts">
              <h3 id="backup-conflicts-title">
                {pluralize(current.conflicts.length, "conflict")}: in both, with different contents
              </h3>
              <ul aria-labelledby="backup-conflicts-title">
                {current.conflicts.map((conflict) => (
                  <li key={`${conflict.section}-${conflict.id}`}>
                    <span className="backup-conflict-section">{sectionLabel(conflict.section)}</span> {conflict.label}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className={blocked ? "backup-notice" : "backup-hint"} role="status">
            {blocked
              ? current.conflicts.length
                ? "This backup can't be restored while these conflicts remain. Nothing has been changed."
                : "This backup can't be restored into this account. Nothing has been changed."
              : nothingToAdd
                ? "Everything in this backup is already in this account."
                : `Restoring adds ${pluralize(counts.total.add, "record")} to ${destination}.`}
          </p>

          <div className="form-actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={!!blocked || !!nothingToAdd || restoring}
              aria-busy={restoring || undefined}
              onClick={() => setConfirming(true)}
            >
              <Icon icon={faUndo} /> {restoring ? "Restoring…" : "Restore"}
            </button>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirming}
        title={`Restore into ${destination}?`}
        body={
          <>
            {counts ? `${pluralize(counts.total.add, "record")} will be added. ` : null}
            This can't be undone from here.
          </>
        }
        confirmLabel="Restore"
        busy={restoring}
        onClose={() => setConfirming(false)}
        onConfirm={() => void restore()}
      />
    </section>
  );
}
