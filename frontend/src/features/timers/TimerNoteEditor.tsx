import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { faClock, faSave } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ApiError } from "@/api/errors";
import { keys } from "@/api/keys";
import type { Timer } from "@/api/types";
import { isNetworkFailure } from "@/lib/offlineQueue";
import { clearNoteDraft, holdNoteDraft, mergeNote, readNoteDraft, writeNoteDraft } from "@/lib/noteDrafts";
import { saveTimerNote } from "./api";

const RETRY_MS = 20_000;

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

/* Notes-as-you-go on a running timer. Every change is written to this device
   at once (lib/noteDrafts) and autosaved 1.5 s after typing stops, with
   If-Match. With no connection, or on a timer that hasn't synced yet, the
   text stays on the device and is retried; a draft left behind (page closed,
   app reopened) is picked up here or sent by the background sync. The
   component owns its text, so the timer poll can never wipe what you are
   typing; a change made elsewhere meanwhile (`autumn note`, another device)
   is joined with it rather than overwritten. */
export function TimerNoteEditor({ timer }: { timer: Timer }) {
  const client = useQueryClient();
  /* The server's note as last known here: what the draft is a change to. */
  const serverNote = useRef(timer.note ?? "");
  const [initial] = useState(() => {
    const draft = readNoteDraft(timer.uuid);
    return draft ? mergeNote(serverNote.current, draft.base, draft.note) : serverNote.current;
  });
  const [value, setValue] = useState(initial);
  const [status, setStatus] = useState<Status>({ text: "Saved", state: "saved" });
  const [saving, setSaving] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const dirty = useRef(false);
  const version = useRef(timer.version);
  const debounce = useRef<number | undefined>(undefined);
  const valueRef = useRef(value);
  valueRef.current = value;

  const edit = (next: string) => {
    setValue(next);
    valueRef.current = next;
    if (timer.uuid) writeNoteDraft({ uuid: timer.uuid, project: timer.project.name, note: next, base: serverNote.current });
    markDirty();
  };

  /* While this editor is open the draft is its to save, not the background sync's. */
  useEffect(() => (timer.uuid ? holdNoteDraft(timer.uuid) : undefined), [timer.uuid]);

  /* A note changed elsewhere (CLI, another device): adopt it while clean,
     join it with the unsaved text otherwise. */
  useEffect(() => {
    version.current = Math.max(version.current, timer.version);
    const server = timer.note ?? "";
    if (server === serverNote.current) return;
    const base = serverNote.current;
    serverNote.current = server;
    if (!dirty.current) setValue(server);
    else edit(mergeNote(server, base, valueRef.current));
  }, [timer.note, timer.version]); // eslint-disable-line react-hooks/exhaustive-deps

  /* A draft restored from the device still has to be saved. */
  useEffect(() => {
    if (initial !== serverNote.current) markDirty();
    return () => window.clearTimeout(debounce.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const retryLater = (text: string) => {
    setStatus({ text, state: "dirty" });
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => void save(), RETRY_MS);
  };

  const save = async () => {
    if (saving || !dirty.current) return;
    if (timer.id < 0) {
      /* Started offline: there is no timer on the server to save to yet. */
      retryLater("Saved on this device. It syncs once the timer does.");
      return;
    }
    setSaving(true);
    const sent = valueRef.current;
    setStatus({ text: "Saving…", state: "dirty" });
    try {
      const saved = await saveTimerNote({ id: timer.id, version: version.current }, sent);
      version.current = saved.version;
      serverNote.current = sent;
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => list?.map((t) => (t.id === saved.id ? { ...t, ...saved } : t)));
      if (valueRef.current === sent) {
        dirty.current = false;
        clearNoteDraft(timer.uuid);
        setStatus({ text: `Saved ✓ ${timestamp().replaceAll("—", "").trim()}`, state: "saved" });
      } else {
        markDirty();
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        /* The refreshed timer arrives through the effect above, which joins the two. */
        retryLater("Changed elsewhere (CLI or another device). Combining both…");
        void client.invalidateQueries({ queryKey: keys.timers() });
      } else if (error instanceof ApiError && isNetworkFailure(error.status)) {
        retryLater("No connection. Saved on this device; it will sync.");
      } else {
        setStatus({ text: "Could not save. Your text is kept on this device; try again.", state: "error" });
      }
    } finally {
      setSaving(false);
    }
  };

  const markDirty = () => {
    dirty.current = true;
    setStatus({ text: "Draft, not saved yet", state: "dirty" });
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
            edit(next.value);
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
        onChange={(event) => edit(event.target.value)}
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
