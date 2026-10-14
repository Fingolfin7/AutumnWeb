import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { faLink, faMicrophone } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "./Icon";

/* The session note editor (session_note_editor.js + the markup the edit-
   session and stop-timer templates wrap around it): a markdown toolbar
   (bold, italic, link), speech dictation where the browser has it, and a
   textarea, all in one bordered shell. Controlled: the caller owns the text.

   Props
     value, onChange   The note text. `onChange(next)` fires for typing,
                       toolbar edits and dictation, always with the full text.
                       A debounced autosave is the caller's business.
     id                Textarea id (default generated); the label points at it.
     label             Caption above the editor; default "Note", null for none
                       (give the caller's own label `htmlFor={id}`).
     placeholder       Default "Note".
     rows              Textarea rows. Default: the stylesheet's 8rem minimum.
     disabled, name, autoFocus, lang (dictation language; falls back to the
                       page language, then the browser's)
     onBlur            Plain textarea blur, e.g. to flush an autosave.
     error             A message or list of messages shown as a field error.
     draftKey          A carry-over key, e.g. a timer id. On mount, a draft
                       stashed for it (see stashNoteDraft) replaces `value`
                       once and is removed, and the status line says so. The
                       timers page stashes the live note when you press Stop;
                       the stop page passes the same key. Mount the editor
                       once the note's starting value is known, so the draft
                       is not overwritten by a late initial value.

   Toolbar: B wraps the selection in **, I in *, the link button asks for a
   URL and inserts [selected or "link text"](url). With nothing selected the
   caret lands between the markers. Ctrl/Cmd+B and Ctrl/Cmd+I do the same.
   Dictation inserts at the caret, replacing the selection, and keeps
   listening across the browser's automatic stops until you press Stop. */

export const NOTE_DRAFT_KEY_PREFIX = "autumn:timer-note-draft:";

/** Stash the current note for the next page to pick up (see `draftKey`). */
export function stashNoteDraft(key: string | number, value: string): void {
  try {
    window.sessionStorage.setItem(NOTE_DRAFT_KEY_PREFIX + key, value);
  } catch {
    /* Storage can be unavailable (locked-down browsers); the server copy remains. */
  }
}

/** Read and remove a stashed draft; null when there is none. */
export function takeNoteDraft(key: string | number): string | null {
  try {
    const stored = window.sessionStorage.getItem(NOTE_DRAFT_KEY_PREFIX + key);
    if (stored === null) return null;
    window.sessionStorage.removeItem(NOTE_DRAFT_KEY_PREFIX + key);
    return stored;
  } catch {
    return null;
  }
}

export function NoteEditor({
  value,
  onChange,
  id,
  label = "Note",
  placeholder = "Note",
  rows,
  disabled,
  name,
  autoFocus,
  lang,
  onBlur,
  error,
  draftKey,
}: {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  label?: string | null;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  name?: string;
  autoFocus?: boolean;
  lang?: string;
  onBlur?: () => void;
  error?: string | string[] | null;
  draftKey?: string | number;
}) {
  const generated = useId();
  const textareaId = id ?? `note-${generated}`;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const supported = dictationSupported();
  const [status, setStatus] = useState(supported ? "" : "Dictation unavailable in this browser.");
  const [dictating, setDictating] = useState(false);

  /* Latest callbacks for the dictation session, which outlives renders. */
  const onChangeRef = useRef(onChange);
  const langRef = useRef(lang);
  useEffect(() => {
    onChangeRef.current = onChange;
    langRef.current = lang;
  });

  const dictation = useRef<Dictation | null>(null);
  useEffect(() => {
    if (!supported) return;
    const controller = createDictation({
      textarea: () => textareaRef.current,
      emit: (next) => onChangeRef.current(next),
      setStatus,
      setDictating,
      language: () => resolveRecognitionLanguage(textareaRef.current, langRef.current),
    });
    dictation.current = controller;
    return () => {
      controller.dispose();
      dictation.current = null;
    };
  }, [supported]);

  useEffect(() => {
    if (draftKey === undefined) return;
    const draft = takeNoteDraft(draftKey);
    if (draft === null) return;
    onChangeRef.current(draft);
    setStatus("Current timer note carried over.");
  }, [draftKey]);

  const apply = (edit: (textarea: HTMLTextAreaElement) => void) => {
    const textarea = textareaRef.current;
    if (!textarea || disabled) return;
    edit(textarea);
    onChange(textarea.value);
    textarea.focus();
  };

  const wrap = (before: string, after: string) =>
    apply((textarea) => {
      const start = textarea.selectionStart || 0;
      const end = textarea.selectionEnd || 0;
      const selected = textarea.value.slice(start, end);
      textarea.setRangeText(`${before}${selected}${after}`, start, end, "end");
      if (!selected) textarea.setSelectionRange(start + before.length, start + before.length);
    });

  const insertLink = () => {
    const textarea = textareaRef.current;
    if (!textarea || disabled) return;
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || 0;
    const selected = textarea.value.slice(start, end) || "link text";
    const url = window.prompt("Enter URL", "https://");
    if (!url) return;
    textarea.setRangeText(`[${selected}](${url})`, start, end, "end");
    onChange(textarea.value);
    textarea.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return;
    if (event.key === "b") {
      event.preventDefault();
      wrap("**", "**");
    } else if (event.key === "i") {
      event.preventDefault();
      wrap("*", "*");
    }
  };

  const errors = error ? (Array.isArray(error) ? error : [error]) : [];

  return (
    <div className="field note-editor-field">
      {label ? <label htmlFor={textareaId}>{label}</label> : null}
      <div className="note-editor-shell">
        <div className="note-editor-toolbar" role="toolbar" aria-label="Note formatting">
          <button type="button" className="note-tool-button" title="Bold (Ctrl+B)" aria-label="Bold" disabled={disabled} onClick={() => wrap("**", "**")}>
            <b>B</b>
          </button>
          <button type="button" className="note-tool-button" title="Italic (Ctrl+I)" aria-label="Italic" disabled={disabled} onClick={() => wrap("*", "*")}>
            <i>I</i>
          </button>
          <button type="button" className="note-tool-button" title="Link" aria-label="Link" disabled={disabled} onClick={insertLink}>
            <Icon icon={faLink} />
          </button>
          <span className="note-toolbar-divider" aria-hidden="true" />
          <button
            type="button"
            className={`note-tool-button dictate-button${dictating ? " listening" : ""}`}
            disabled={disabled || !supported}
            aria-pressed={supported ? dictating : undefined}
            onClick={() => dictation.current?.toggle()}
          >
            <Icon icon={faMicrophone} />
            <span>{!supported ? "Unavailable" : dictating ? "Stop" : "Dictate"}</span>
          </button>
        </div>
        <textarea
          ref={textareaRef}
          id={textareaId}
          name={name}
          value={value}
          rows={rows}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          lang={lang}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          onKeyDown={onKeyDown}
        />
      </div>
      <small data-note-status="" aria-live="polite">
        {status}
      </small>
      {errors.length ? (
        <ul className="errorlist">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/* ----- Dictation ---------------------------------------------------------
   The Web Speech API is only in Chromium and Safari (webkit-prefixed). The
   typings aren't in lib.dom, so the slice used here is declared. */

interface RecognitionResult {
  isFinal: boolean;
  0?: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onresult: ((event: RecognitionEvent) => void) | null;
  onaudiostart: (() => void) | null;
  onsoundstart: (() => void) | null;
  onspeechstart: (() => void) | null;
  onspeechend: (() => void) | null;
}
type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | undefined {
  if (typeof window === "undefined") return undefined;
  const w = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export function dictationSupported(): boolean {
  return recognitionConstructor() !== undefined;
}

/* "en" -> "en-US", "fr" -> "fr-FR", "pt-BR" stays. First usable of: the
   textarea's/prop language, the page's, the browser's. */
export function resolveRecognitionLanguage(textarea: HTMLTextAreaElement | null, lang?: string): string {
  const candidates = [
    lang,
    textarea?.getAttribute("lang"),
    typeof document !== "undefined" ? document.documentElement.lang : null,
    typeof navigator !== "undefined" ? navigator.language : null,
    typeof navigator !== "undefined" && navigator.languages?.length ? navigator.languages[0] : null,
  ];
  for (const candidate of candidates) {
    const normalized = candidate ? String(candidate).trim() : "";
    if (!normalized) continue;
    if (/^[a-z]{2}$/i.test(normalized)) {
      return normalized.toLowerCase() === "en" ? "en-US" : `${normalized.toLowerCase()}-${normalized.toUpperCase()}`;
    }
    return normalized;
  }
  return "en-US";
}

function joinTranscriptParts(left: string, right: string): string {
  if (!left) return right || "";
  if (!right) return left;
  return `${left} ${right}`.trim();
}

interface Dictation {
  toggle(): void;
  dispose(): void;
}

function createDictation(deps: {
  textarea: () => HTMLTextAreaElement | null;
  emit: (value: string) => void;
  setStatus: (message: string) => void;
  setDictating: (value: boolean) => void;
  language: () => string;
}): Dictation {
  const Ctor = recognitionConstructor()!;
  const recognition = new Ctor();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  let listening = false;
  let shouldListen = false;
  let restartTimer: number | null = null;
  let anchorStart: number | null = null;
  let anchorEnd: number | null = null;
  let committed = "";
  let finalStatus = "";

  const clearRestart = () => {
    if (restartTimer !== null) {
      window.clearTimeout(restartTimer);
      restartTimer = null;
    }
  };

  const setIdle = (message: string) => {
    listening = false;
    deps.setDictating(false);
    deps.setStatus(finalStatus || message);
  };

  const resetTranscript = () => {
    anchorStart = null;
    anchorEnd = null;
    committed = "";
    finalStatus = "";
  };

  const stop = (message?: string) => {
    shouldListen = false;
    clearRestart();
    if (listening) recognition.stop();
    else setIdle(message || "Dictation stopped.");
  };

  /* Insert the transcript so far at the caret captured when it began; each
     update replaces the previous insertion. */
  const render = (interim: string) => {
    const textarea = deps.textarea();
    if (!textarea) return;
    if (anchorStart === null || anchorEnd === null) {
      anchorStart = textarea.selectionStart || textarea.value.length;
      anchorEnd = textarea.selectionEnd || anchorStart;
    }
    const transcript = joinTranscriptParts(committed, interim || "").trim();
    if (!transcript) return;
    const start = anchorStart;
    const end = anchorEnd;
    const needsLeadingSpace = start > 0 && !/\s$/.test(textarea.value.slice(0, start));
    const insertion = `${needsLeadingSpace ? " " : ""}${transcript}`;
    textarea.setRangeText(insertion, start, end, "end");
    anchorEnd = start + insertion.length;
    deps.emit(textarea.value);
    textarea.focus();
  };

  recognition.onstart = () => {
    listening = true;
    finalStatus = "";
    deps.setDictating(true);
    deps.setStatus("Listening...");
  };

  recognition.onend = () => {
    clearRestart();
    if (!shouldListen) {
      setIdle("Dictation stopped.");
      resetTranscript();
      return;
    }
    /* Browsers end a continuous session after a pause; pick it back up. */
    listening = false;
    deps.setStatus("Still listening...");
    restartTimer = window.setTimeout(() => {
      if (shouldListen && !listening) recognition.start();
    }, 150);
  };

  recognition.onaudiostart = () => deps.setStatus("Microphone connected. Listening...");
  recognition.onsoundstart = () => deps.setStatus("Sound detected...");
  recognition.onspeechstart = () => deps.setStatus("Speech detected...");
  recognition.onspeechend = () => deps.setStatus("Speech ended. Processing...");

  recognition.onerror = (event) => {
    const code = event?.error ?? "unknown";
    if (code === "no-speech") {
      deps.setStatus("No speech detected. Keep talking or try again.");
      return;
    }
    if (code === "aborted") {
      finalStatus = "Dictation stopped.";
      setIdle("Dictation stopped.");
      resetTranscript();
      return;
    }
    if (code === "not-allowed" || code === "service-not-allowed") {
      finalStatus = "Microphone access was blocked. Please allow microphone permissions and try again.";
      stop(finalStatus);
      return;
    }
    finalStatus = `Dictation error (${code}). Please try again.`;
    stop(finalStatus);
  };

  recognition.onresult = (event) => {
    let finalTranscript = "";
    let interim = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const chunk = result?.[0]?.transcript.trim();
      if (!result || !chunk) continue;
      if (result.isFinal) finalTranscript = joinTranscriptParts(finalTranscript, chunk);
      else interim = joinTranscriptParts(interim, chunk);
    }
    if (finalTranscript) committed = joinTranscriptParts(committed, finalTranscript);
    if (!committed && !interim) return;
    render(interim);
    deps.setStatus(shouldListen ? "Listening..." : "Added dictated text.");
  };

  return {
    toggle() {
      if (shouldListen) {
        stop("Dictation stopped.");
        return;
      }
      resetTranscript();
      shouldListen = true;
      recognition.lang = deps.language();
      try {
        recognition.start();
      } catch {
        /* start() throws if a session is already running; onend restarts it. */
      }
    },
    dispose() {
      shouldListen = false;
      clearRestart();
      recognition.onstart = recognition.onend = recognition.onerror = recognition.onresult = null;
      recognition.onaudiostart = recognition.onsoundstart = recognition.onspeechstart = recognition.onspeechend = null;
      try {
        recognition.abort();
      } catch {
        /* nothing to abort */
      }
    },
  };
}
