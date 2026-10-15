import { useMutation, useQueryClient } from "@tanstack/react-query";
import { faBell, faStopwatch, faTimes } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { api, unwrap } from "@/api/client";
import { errorMessage } from "@/api/errors";
import { useToast } from "@/app/toasts";
import { keys } from "@/api/keys";
import { useInvalidate } from "@/api/sync";
import type { Timer } from "@/api/types";

const MODE_LABEL: Record<string, string> = { after: "Once after", interval: "Every", at: "At" };

function nextLabel(iso: string) {
  const date = new Date(iso);
  return `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })}`;
}

/* A running timer's pending reminders with Cancel (.rm-live). They come
   embedded in the timers list (?include=reminders). */
export function TimerReminders({ timer }: { timer: Timer }) {
  const client = useQueryClient();
  const invalidate = useInvalidate();
  const toast = useToast();
  const cancel = useMutation({
    mutationFn: (reminderId: number) =>
      unwrap(
        api.DELETE("/api/v2/timers/{session_id}/reminders/{reminder_id}", {
          params: { path: { session_id: timer.id, reminder_id: reminderId } },
        }),
      ),
    onMutate: (reminderId) => {
      client.setQueriesData<Timer[]>({ queryKey: keys.timers() }, (list) =>
        list?.map((t) =>
          t.id === timer.id ? { ...t, active_reminders: (t.active_reminders ?? []).filter((r) => r.id !== reminderId) } : t,
        ),
      );
    },
    onError: (error) => toast.error(`Couldn't cancel the reminder: ${errorMessage(error)}`),
    onSettled: () => invalidate("timers"),
  });

  const list = timer.active_reminders ?? [];
  const notifyOnAutoStop = timer.notify_on_auto_stop;
  if (!list.length && !notifyOnAutoStop) return null;
  return (
    <div className="rm-live" aria-label="Timer reminders">
      {list.map((reminder) => (
        <div className="rm-live-row" key={reminder.id}>
          <div className="rm-live-copy">
            <span className="rm-live-mode">
              <Icon icon={faBell} /> {MODE_LABEL[reminder.mode] ?? reminder.mode}
            </span>
            <span className="rm-live-next">
              Next <span className="mono">{nextLabel(reminder.next_fire_at)}</span>
            </span>
            {reminder.message ? <span className="rm-live-message">{reminder.message}</span> : null}
          </div>
          <button
            type="button"
            className="btn btn--quiet rm-live-cancel"
            disabled={cancel.isPending && cancel.variables === reminder.id}
            onClick={() => cancel.mutate(reminder.id)}
          >
            <Icon icon={faTimes} /> Cancel
          </button>
        </div>
      ))}
      {notifyOnAutoStop ? (
        <div className="rm-live-row rm-live-row--auto-stop">
          <div className="rm-live-copy">
            <span className="rm-live-mode">
              <Icon icon={faStopwatch} /> Auto-stop
            </span>
            <span className="rm-live-next">Notify when this timer stops itself</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
