import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { NoteEditor, stashNoteDraft, takeNoteDraft } from "@/components/NoteEditor";
import { useNoteDraft, readNoteDraft } from "@/lib/noteDraft";
import { formatDate, formatDuration, elapsedSeconds } from "@/lib/format";
import { keys } from "@/api/keys";
import type { Timer } from "@/api/types";
import { saveTimerNote } from "./api";

export function TimerNoteEditor({ timer, registerStash, preview }: {
  timer: Timer;
  preview?: boolean;
  registerStash?: (stash: () => void) => void;
}) {
  const client = useQueryClient();
  const draftKey = `session:${timer.uuid ?? timer.id}`;
  const draft = useNoteDraft({
    draftKey, text: timer.note ?? "", version: timer.version,
    enabled: timer.id > 0 && !timer.pending_sync, revision: timer.id,
    save: async (note, version) => {
      const saved = await saveTimerNote({ id: timer.id, version }, note);
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) => list?.map((item) => item.id === saved.id ? { ...item, ...saved } : item));
      return saved;
    },
  });
  useEffect(() => {
    const legacy = takeNoteDraft(timer.uuid ?? timer.id) ?? takeNoteDraft(timer.id);
    if (!readNoteDraft(draftKey) && legacy !== null && legacy !== draft.value) draft.change(legacy);
  }, []);
  useEffect(() => {
    registerStash?.(() => {
      // Stop reads this synchronously, before the autosave or route can settle.
      stashNoteDraft(timer.id, draft.value);
      if (timer.uuid) stashNoteDraft(timer.uuid, draft.value);
    });
  }, [registerStash, timer.id, timer.uuid, timer.version, draftKey, draft.value]);
  return <div className="timer-note-editor"><NoteEditor preview={preview} id={`timer-note-${timer.id}`} label="Session note" sessionTitle={`${timer.project.name} ? ${formatDate(timer.start)} ? ${formatDuration(elapsedSeconds(timer.start, Date.now()) / 60)}`} disabled={timer.id < 0 && !timer.pending_sync} value={draft.value} onChange={draft.change} onBlur={() => void draft.flush()} saveStatus={draft.status} onRetry={() => void draft.flush()} rows={3} placeholder="Jot down progress while this timer runs." /></div>;
}
