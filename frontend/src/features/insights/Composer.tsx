import { useEffect, useLayoutEffect, useRef, type ClipboardEvent, type FormEvent, type KeyboardEvent } from "react";
import { faPaperclip, faPaperPlane, faStop } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { effortLabel, effortsFor, openaiConnectionNote, pickEffort, providerLabel, type ModelSelection } from "./logic";
import type { InsightOptions } from "./types";
import { AttachmentTray } from "./AttachmentList";
import { ACCEPT, MAX_FILES, type Draft } from "./attachments";

/* Model pickers, attached files, the question box and Send. */
export function Composer({
  prompt,
  onPrompt,
  busy,
  onSend,
  onStop,
  drafts,
  uploading,
  onAddFiles,
  onRemoveDraft,
}: {
  prompt: string;
  onPrompt: (value: string) => void;
  busy: boolean;
  onSend: () => void;
  onStop: () => void;
  drafts: Draft[];
  uploading: boolean;
  onAddFiles: (files: File[]) => void;
  onRemoveDraft: (key: string) => void;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const canSend = !!prompt.trim() && !busy && !uploading;
  /* Auto-grow up to ~7 lines. */
  useLayoutEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.max(72, Math.min(node.scrollHeight, 176))}px`;
  }, [prompt]);

  // Toasts clear the complete composer, including a changing attachment tray.
  useLayoutEffect(() => {
    const form = textarea.current?.closest("form");
    if (!form) return;
    const toast = document.querySelector(".toast-region");
    const place = () => {
      document.documentElement.style.setProperty("--composer-clearance", `${Math.max(0, window.innerHeight - form.getBoundingClientRect().top) + 12}px`);
      const height = toast?.getBoundingClientRect().height ?? 0;
      document.documentElement.style.setProperty("--insights-toast-clearance", `${height ? height + 24 : 0}px`);
    };
    const observer = new ResizeObserver(place);
    if (toast) observer.observe(toast);
    observer.observe(form); window.addEventListener("resize", place); window.visualViewport?.addEventListener("resize", place); place();
    return () => { observer.disconnect(); window.removeEventListener("resize", place); window.visualViewport?.removeEventListener("resize", place); document.documentElement.style.removeProperty("--composer-clearance"); document.documentElement.style.removeProperty("--insights-toast-clearance"); };
  }, []);

  /* Hand the cursor back when an answer finishes. */
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (wasBusy.current && !busy) textarea.current?.focus();
    wasBusy.current = busy;
  }, [busy]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canSend) onSend();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !busy) {
      event.preventDefault();
      if (canSend) onSend();
    }
  };
  /* A pasted screenshot becomes an attachment. Copying text out of Word or a
     web page can carry a picture of it too: text wins then. */
  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const data = event.clipboardData;
    if (!data?.files.length || data.getData("text/plain")) return;
    event.preventDefault();
    onAddFiles(Array.from(data.files));
  };
  const full = drafts.length >= MAX_FILES;

  return (
    <form className="composer" onSubmit={submit}>
      <AttachmentTray drafts={drafts} onRemove={onRemoveDraft} />

      <div className="composer-input-row">
        <input
          ref={picker}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(event) => {
            onAddFiles(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className="composer-attach"
          onClick={() => picker.current?.click()}
          disabled={busy || full}
          title={full ? `Up to ${MAX_FILES} files per message` : "Attach screenshots, PDFs, Word docs or transcripts (or paste and drop them)"}
          aria-label="Attach files"
        >
          <Icon icon={faPaperclip} />
        </button>
        <label className="sr-only" htmlFor="prompt">
          Your question
        </label>
        <textarea
          id="prompt"
          name="prompt"
          ref={textarea}
          rows={2}
          placeholder={drafts.length ? "Ask about these files…" : "Ask about your time…"}
          value={prompt}
          readOnly={busy}
          onChange={(e) => onPrompt(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
        />
        {busy ? (
          <button type="button" className="btn btn--ghost" aria-label="Stop the answer" title="Stop the answer" onClick={onStop}>
            <Icon icon={faStop} /> <span className="composer-btn-label">Stop</span>
          </button>
        ) : (
          <button type="submit" className="btn btn--primary" aria-label="Send question" title={uploading ? "Waiting for files to finish uploading" : "Send (Enter)"} disabled={!canSend}>
            <Icon icon={faPaperPlane} /> <span className="composer-btn-label">Send</span>
          </button>
        )}
      </div>
    </form>
  );
}

export function ModelPicker({ options, selection, onSelection, busy }: { options: InsightOptions; selection: ModelSelection; onSelection: (next: ModelSelection) => void; busy: boolean }) {
  const provider = options.providers.find((p) => p.provider === selection.provider);
  const efforts = effortsFor(options, selection.provider, selection.model);
  const note = openaiConnectionNote(options.openai_source, options.providers.some((p) => p.provider === "openai"));

  const pickProvider = (name: string) => {
    const next = options.providers.find((p) => p.provider === name);
    const model = next?.models[0];
    if (!next || !model) return;
    onSelection({ provider: name, model: model.value, effort: pickEffort(model.reasoning_efforts, "high") });
  };
  const pickModel = (value: string) => {
    onSelection({ ...selection, model: value, effort: pickEffort(effortsFor(options, selection.provider, value), selection.effort) });
  };

  return (
<div className="composer-toolbar">
        <span className="composer-field">
          <label htmlFor="provider">Provider</label>
          <select id="provider" name="provider" value={selection.provider} onChange={(e) => pickProvider(e.target.value)} disabled={busy}>
            {options.providers.map((p) => (
              <option key={p.provider} value={p.provider}>
                {providerLabel(p.provider)}
              </option>
            ))}
          </select>
        </span>

        <span className="composer-field">
          <label htmlFor="model">Model</label>
          <select id="model" name="model" value={selection.model} onChange={(e) => pickModel(e.target.value)} disabled={busy}>
            {(provider?.models ?? []).map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </span>

        {efforts.length ? (
          <span className="composer-field" id="reasoning-effort-field">
            <label htmlFor="reasoning_effort" title="OpenAI reasoning effort">
              Effort
            </label>
            <select id="reasoning_effort" name="reasoning_effort" value={selection.effort} onChange={(e) => onSelection({ ...selection, effort: e.target.value })} disabled={busy}>
              {efforts.map((effort) => (
                <option key={effort} value={effort}>
                  {effortLabel(effort)}
                </option>
              ))}
            </select>
          </span>
        ) : null}

        {note ? (
          <span className="composer-note muted" title={note.title}>
            {note.text}
            {note.profileLink ? (
              <>
                {" "}
                <AppLink href={urls.profile()} className="plain-link">
                  Profile
                </AppLink>
                .
              </>
            ) : null}
          </span>
        ) : null}
      </div>
  );
}
