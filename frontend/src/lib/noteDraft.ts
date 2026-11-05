import { useEffect, useRef, useState } from "react";
import { bootstrap } from "@/bootstrap";
import { ApiError } from "@/api/errors";

type Draft = { text: string; version: number };
const keyFor = (key: string) => `autumn:note:${bootstrap().user.id}:${key}`;
const memory = new Map<string, Draft>();

export function readNoteDraft(key: string): Draft | null {
  try {
    const raw = localStorage.getItem(keyFor(key));
    if (raw) {
      const draft = JSON.parse(raw) as Draft;
      if (typeof draft.text === "string" && typeof draft.version === "number") return draft;
    }
  } catch { /* The in-memory draft remains usable when storage is unavailable. */ }
  return memory.get(keyFor(key)) ?? null;
}

export function writeNoteDraft(key: string, draft: Draft) {
  memory.set(keyFor(key), draft);
  try { localStorage.setItem(keyFor(key), JSON.stringify(draft)); } catch { /* Keep the memory copy. */ }
}

export function clearNoteDraft(key: string, text?: string) {
  // An older request must never remove a more recent edit.
  if (text !== undefined && readNoteDraft(key)?.text !== text) return;
  memory.delete(keyFor(key));
  try { localStorage.removeItem(keyFor(key)); } catch { /* Storage unavailable. */ }
}

/** One serialized autosave, shared by running and saved journals. The draft
 * retains its original version across reloads: CLI edits still cause a 409. */
export function useNoteDraft({ draftKey, text, version, save, enabled = true, revision }: {
  draftKey: string;
  text: string;
  version: number;
  save: (text: string, version: number) => Promise<{ version: number }>;
  enabled?: boolean;
  revision?: number;
}) {
  const [value, setValue] = useState(() => readNoteDraft(draftKey)?.text ?? text);
  const [status, setStatus] = useState(value === text ? "Saved" : "Unsaved changes · kept on this device");
  const latest = useRef(value);
  const baseline = useRef(text);
  const match = useRef(readNoteDraft(draftKey)?.version ?? version);
  const pending = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const options = useRef({ save, enabled });
  options.current = { save, enabled };
  const mounted = useRef(true);
  const report = (message: string) => { if (mounted.current) setStatus(message); };

  const flush = (): Promise<boolean> => {
    clearTimeout(timer.current);
    if (pending.current) return pending.current.then((ok) => ok ? flush() : false);
    if (latest.current === baseline.current) return Promise.resolve(true);
    if (!options.current.enabled || !navigator.onLine) {
      report("Unsaved changes · kept on this device");
      return Promise.resolve(false);
    }
    const sent = latest.current;
    report("Saving…");
    const run = async () => {
      try {
        const saved = await options.current.save(sent, match.current);
        baseline.current = sent;
        match.current = saved.version;
        if (latest.current === sent) {
          clearNoteDraft(draftKey, sent);
          report("Saved");
        } else {
          writeNoteDraft(draftKey, { text: latest.current, version: saved.version });
        }
        return true;
      } catch (error) {
        report(error instanceof ApiError && error.status === 409
          ? "Unsaved changes · changed elsewhere. Your draft is kept here; review the latest before replacing it."
          : "Unsaved changes · kept on this device. Reconnect or retry.");
        return false;
      } finally { pending.current = null; }
    };
    pending.current = run();
    return pending.current.then((ok) => ok && latest.current !== sent ? flush() : ok);
  };
  const flushRef = useRef(flush);
  flushRef.current = flush;

  const change = (next: string) => {
    latest.current = next;
    setValue(next);
    writeNoteDraft(draftKey, { text: next, version: match.current });
    report(next === baseline.current ? "Saved" : "Unsaved changes · kept on this device");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void flushRef.current(), 1200);
  };

  useEffect(() => {
    // Polls can update a clean editor, never the text being written.
    if (!pending.current && latest.current === baseline.current) {
      baseline.current = text;
      latest.current = text;
      match.current = version;
      setValue(text);
    }
  }, [text, version]);
  useEffect(() => {
    if (enabled && latest.current !== baseline.current) void flushRef.current();
  }, [enabled, revision]);
  useEffect(() => {
    mounted.current = true;
    const retry = () => void flushRef.current();
    window.addEventListener("online", retry);
    return () => {
      mounted.current = false;
      clearTimeout(timer.current);
      window.removeEventListener("online", retry);
    };
  }, []);

  const accept = (next: string, nextVersion: number) => {
    baseline.current = next;
    match.current = nextVersion;
    if (latest.current === next) { clearNoteDraft(draftKey, next); report("Saved"); }
    else writeNoteDraft(draftKey, { text: latest.current, version: nextVersion });
  };
  return { value, change, status, flush, accept };
}
