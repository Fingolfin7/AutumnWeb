import { useEffect, useRef, useState } from "react";
import { errorMessage } from "@/api/errors";
import { useToast } from "@/app/toasts";
import { saveBlob } from "@/features/import-export/download";
import { Dialog } from "./Sheet";

const markdownBlob = (text: string) => new Blob([text], { type: "text/markdown;charset=utf-8" });

function copyText(text: Promise<string>) {
  if (navigator.clipboard?.write && typeof ClipboardItem !== "undefined") {
    // Start the clipboard write in the click handler. Some browsers require
    // that gesture even when the text still needs to be fetched.
    const content = text.then((value) => new Blob([value], { type: "text/plain" }));
    void content.catch(() => undefined);
    return navigator.clipboard.write([new ClipboardItem({ "text/plain": content })]);
  }
  return text.then((value) => navigator.clipboard.writeText(value));
}

export function MarkdownActions({ copyLabel, filename, load, disabled, showDownload }: {
  copyLabel: string;
  filename: string;
  load: (signal: AbortSignal) => Promise<string>;
  disabled?: boolean;
  showDownload?: boolean;
}) {
  const toast = useToast();
  const operation = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState<"copy" | "download" | null>(null);
  const [manualCopy, setManualCopy] = useState<string | null>(null);
  const [copyFailed, setCopyFailed] = useState(false);
  useEffect(() => () => operation.current?.abort(), []);

  const run = async (action: "copy" | "download") => {
    if (disabled || operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    const { signal } = controller;
    setBusy(action);
    const text = Promise.resolve().then(() => load(signal)).then((value) => {
      signal.throwIfAborted();
      return value;
    });
    try {
      if (action === "download") {
        saveBlob(markdownBlob(await text), filename);
      } else {
        try {
          await copyText(text);
          if (!signal.aborted) toast.success("Copied as Markdown.");
        } catch {
          setCopyFailed(false);
          setManualCopy(await text);
        }
      }
    } catch (error) {
      if (!signal.aborted) toast.error(errorMessage(error));
    } finally {
      operation.current = null;
      if (!signal.aborted) setBusy(null);
    }
  };

  const copyPrepared = async () => {
    if (manualCopy === null) return;
    try {
      await navigator.clipboard.writeText(manualCopy);
      toast.success("Copied as Markdown.");
      setManualCopy(null);
    } catch {
      setCopyFailed(true);
    }
  };

  return (
    <div className="markdown-actions" aria-busy={!!busy}>
      <button className="btn btn--quiet" type="button" aria-disabled={disabled || !!busy} onClick={() => void run("copy")}>
        {busy === "copy" ? "Preparing…" : copyLabel}
      </button>
      {showDownload ? (
        <button className="btn btn--quiet" type="button" aria-disabled={disabled || !!busy} onClick={() => void run("download")}>
          {busy === "download" ? "Preparing…" : "Download .md"}
        </button>
      ) : null}
      <Dialog open={manualCopy !== null} onClose={() => setManualCopy(null)} title="Copy Markdown" wide>
        {copyFailed ? <p role="status">Clipboard access is unavailable. Select the text to copy it manually, or download the file.</p> : null}
        <textarea className="markdown-copy-text" aria-label="Markdown" data-autofocus readOnly rows={12} value={manualCopy ?? ""} onFocus={(event) => event.currentTarget.select()} />
        <div className="dialog-actions">
          <button className="btn btn--quiet" type="button" onClick={() => saveBlob(markdownBlob(manualCopy ?? ""), filename)}>Download .md</button>
          <button className="btn btn--primary" type="button" onClick={() => void copyPrepared()}>Copy</button>
          <button className="btn btn--ghost" type="button" onClick={() => setManualCopy(null)}>Done</button>
        </div>
      </Dialog>
    </div>
  );
}
