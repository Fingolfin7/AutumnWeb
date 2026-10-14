import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { faClock, faSave } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import type { Timer } from "@/api/types";
import { saveTimerNote } from "./api";
import { NOTE_DRAFT_KEY_PREFIX } from "./FocusCard";

type Status = { text: string; state: "saved" | "dirty" | "error" };

const pad = (n: number) => String(n).padStart(2, "0");
export const timestamp = (date = new Date()) => `— ${pad(date.getHours())}:${pad(date.getMinutes())} —`;

/* Insert "— HH:MM — " at the caret, on its own line (timer_notes.js). */
export function insertStamp(value: string, caret: number, stamp = timestamp()): { value: string; caret: number } {
  const before = value.slice(0, caret);
  const after = value.slice(caret);
  const insertion = `${before && !before.endsWith("\n") ? "\n" : ""}${stamp} `;
  return { value: before + insertion + after, caret: before.length + insertion.length };
}

/* Notes-as-you-go on a running timer. Autosaves 1.5 s after typing stops
   (with If-Match, so an `autumn note` from the CLI in the meantime is
   reported rather than overwritten). The component owns its text, so the
   timer poll can never wipe what you are typing: no dirty-editor guard
   needed. Unsaved text is stashed for the stop page via `stash()`. */
export function TimerNoteEditor({ timer, registerStash }: { timer: Timer; registerStash?: (stash: () => void) => void }) {
  const client = useQueryClient();
  const [value, setValue] = useState(timer.note ?? "");
  const [status, setStatus] = useState<Status>({ text: "Saved", state: "saved" });
  const [saving, setSaving] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const dirty = useRef(false);
  const version = useRef(timer.version);
  const debounce = useRef<number | undefined>(undefined);
  const valueRef = useRef(value);
  valueRef.current = value;

  /* Adopt server-side note changes (CLI, another device) only while clean. */
  useEffect(() => {
    version.current = Math.max(version.current, timer.version);
    if (!dirty.current && (timer.note ?? "") !== valueRef.current) setValue(timer.note ?? "");
  }, [timer.note, timer.version]);

  useEffect(() => {
    registerStash?.(() => {
      try {
        window.sessionStorage.setItem(NOTE_DRAFT_KEY_PREFIX + timer.id, valueRef.current);
      } catch {
        /* storage unavailable */
      }
    });
  }, [registerStash, timer.id]);

  useEffect(() => () => window.clearTimeout(debounce.current), []);

  const save = async () => {
    if (saving || !dirty.current || timer.id < 0) return;
    setSaving(true);
    const sent = valueRef.current;
    setStatus({ text: "Saving…", state: "dirty" });
    try {
      const saved = await saveTimerNote({ id: timer.id, version: version.current }, sent);
      version.current = saved.version;
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => list?.map((t) => (t.id === saved.id ? { ...t, ...saved } : t)));
      if (valueRef.current === sent) {
        dirty.current = false;
        setStatus({ text: `Saved ✓ ${timestamp().replaceAll("—", "").trim()}`, state: "saved" });
      } else {
        markDirty();
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setStatus({ text: "Changed elsewhere (CLI or another device). Copy your text, then reload.", state: "error" });
      } else if (error instanceof ApiError && error.status === 0) {
        setStatus({ text: "Offline — will retry when you edit again", state: "error" });
      } else {
        setStatus({ text: "Could not save — try again", state: "error" });
      }
    } finally {
      setSaving(false);
    }
  };

  const markDirty = () => {
    dirty.current = true;
    setStatus({ text: "Draft — not saved", state: "dirty" });
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => void save(), 1500);
  };

  return (
    <div className="timer-note-editor">
      <label htmlFor={`timer-note-${timer.id}`}>Session note</label>
      <div className="timer-note-toolbar">
        <button
          type="button"
          className="attr-mini-btn"
          onClick={() => {
            const node = textarea.current;
            const next = insertStamp(value, node?.selectionStart ?? value.length);
            setValue(next.value);
            markDirty();
            requestAnimationFrame(() => {
              node?.focus();
              node?.setSelectionRange(next.caret, next.caret);
            });
          }}
        >
          <Icon icon={faClock} /> Insert timestamp
        </button>
      </div>
      <textarea
        ref={textarea}
        id={`timer-note-${timer.id}`}
        placeholder="Jot down progress while this timer runs."
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          markDirty();
        }}
      />
      <div className="timer-note-footer">
        <small className={`timer-note-status${status.state === "saved" ? " saved" : status.state === "error" ? " error" : ""}`} role="status">
          {status.text}
        </small>
        <button
          type="button"
          className="attr-mini-btn timer-note-save"
          disabled={saving}
          onClick={() => {
            window.clearTimeout(debounce.current);
            dirty.current = true;
            void save();
          }}
        >
          <Icon icon={faSave} /> Save note
        </button>
      </div>
    </div>
  );
}
