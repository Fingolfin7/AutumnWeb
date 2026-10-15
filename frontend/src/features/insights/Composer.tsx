import { useEffect, useLayoutEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { faPaperPlane, faStop } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { AppLink, urls } from "@/app/links";
import { effortLabel, effortsFor, pickEffort, providerLabel, type ModelSelection } from "./logic";
import type { InsightOptions } from "./types";

/* Model pickers, the question box and Send. */
export function Composer({
  options,
  selection,
  onSelection,
  prompt,
  onPrompt,
  busy,
  onSend,
  onStop,
}: {
  options: InsightOptions;
  selection: ModelSelection;
  onSelection: (next: ModelSelection) => void;
  prompt: string;
  onPrompt: (value: string) => void;
  busy: boolean;
  onSend: () => void;
  onStop: () => void;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const provider = options.providers.find((p) => p.provider === selection.provider);
  const efforts = effortsFor(options, selection.provider, selection.model);
  const hasOpenai = options.providers.some((p) => p.provider === "openai");

  /* Auto-grow up to ~7 lines. */
  useLayoutEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 176)}px`;
  }, [prompt]);

  /* Hand the cursor back when an answer finishes. */
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (wasBusy.current && !busy) textarea.current?.focus();
    wasBusy.current = busy;
  }, [busy]);

  const pickProvider = (name: string) => {
    const next = options.providers.find((p) => p.provider === name);
    const model = next?.models[0];
    if (!next || !model) return;
    onSelection({ provider: name, model: model.value, effort: pickEffort(model.reasoning_efforts, "high") });
  };
  const pickModel = (value: string) => {
    onSelection({ ...selection, model: value, effort: pickEffort(effortsFor(options, selection.provider, value), selection.effort) });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (prompt.trim()) onSend();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !busy) {
      event.preventDefault();
      if (prompt.trim()) onSend();
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
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

        {!hasOpenai ? (
          <span className="composer-note muted" title="OpenAI models need an API key or Codex login.">
            OpenAI needs a key or Codex login &mdash; add one in{" "}
            <AppLink href={urls.profile()} className="plain-link">
              Profile
            </AppLink>
            .
          </span>
        ) : null}
      </div>

      <div className="composer-input-row">
        <label className="sr-only" htmlFor="prompt">
          Your question
        </label>
        <textarea
          id="prompt"
          name="prompt"
          ref={textarea}
          rows={1}
          placeholder="Ask a question about your sessions…"
          value={prompt}
          readOnly={busy}
          onChange={(e) => onPrompt(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {busy ? (
          <button type="button" className="btn btn--ghost" title="Stop the answer" onClick={onStop}>
            <Icon icon={faStop} /> Stop
          </button>
        ) : (
          <button type="submit" className="btn btn--primary" title="Send (Enter)" disabled={!prompt.trim()}>
            <Icon icon={faPaperPlane} /> Send
          </button>
        )}
      </div>
    </form>
  );
}
