import { useId, useMemo, useState } from "react";
import {
  localTimeCandidates,
  nonexistentTimeMessage,
  occurrenceLabel,
  parseInstant,
  toDateTimeLocal,
  type LocalTimeCandidates,
} from "@/lib/format";

/* A datetime-local value is a wall time, and twice a year the wall time is
   not one instant: clocks going back repeat an hour, clocks going forward
   skip one. `useLocalTime` resolves a field's value to the instant to submit
   (asking which occurrence when it is repeated, refusing when it is skipped);
   `LocalTimeNotice` sits under the input and shows the choice or the error. */

export interface LocalTimeField {
  value: string;
  candidates: LocalTimeCandidates;
  /** Which occurrence of a repeated time is chosen (0 = first). */
  index: number;
  setIndex: (index: number) => void;
  /** The instant to submit, or null if the field is empty, invalid or skipped. */
  instant: string | null;
  /** Set when the wall time does not exist; submit must be blocked. */
  error: string | null;
}

/** `original` is the instant the field was filled from. While the value is
 *  still that instant's wall time, a repeated time defaults to the occurrence
 *  it came from instead of the first, so an untouched field keeps its meaning. */
export function useLocalTime(value: string, original?: string | null): LocalTimeField {
  const candidates = useMemo(() => localTimeCandidates(value), [value]);
  const [pick, setPick] = useState<{ value: string; index: number } | null>(null);

  const defaultIndex = useMemo(() => {
    if (candidates.kind !== "ambiguous" || !original) return 0;
    const date = parseInstant(original);
    if (!date || toDateTimeLocal(date, true) !== value) return 0;
    const second = Math.floor(date.getTime() / 1000);
    const found = candidates.instants.findIndex((iso) => Math.floor(new Date(iso).getTime() / 1000) === second);
    return found < 0 ? 0 : found;
  }, [candidates, original, value]);

  const index = pick && pick.value === value ? pick.index : defaultIndex;
  const error = candidates.kind === "nonexistent" ? nonexistentTimeMessage(value) : null;
  const instant = candidates.kind === "nonexistent" ? null : (candidates.instants[index] ?? candidates.instants[0] ?? null);

  return { value, candidates, index, setIndex: (next) => setPick({ value, index: next }), instant, error };
}

/** Choice between the two occurrences, or the field error. Renders nothing
 *  for an ordinary time, so the normal case looks the same as before. */
export function LocalTimeNotice({ field, label }: { field: LocalTimeField; label: string }) {
  const hintId = useId();
  if (field.error) {
    return (
      <ul className="errorlist" role="alert">
        <li>{field.error}</li>
      </ul>
    );
  }
  if (field.candidates.kind !== "ambiguous") return null;
  const time = field.value.slice(11);
  const clock = time.length === 8 && time.endsWith(":00") ? time.slice(0, 5) : time;
  return (
    <div className="local-time-notice">
      <p className="rm-note" id={hintId}>
        {clock} happens twice here because the clocks go back. Which one is {label}?
      </p>
      <div className="preset-row" role="group" aria-labelledby={hintId}>
        {field.candidates.instants.map((instant, i) => (
          <button
            key={instant}
            type="button"
            className="timer-preset-button"
            aria-pressed={field.index === i}
            onClick={() => field.setIndex(i)}
          >
            {occurrenceLabel(i, instant)}
          </button>
        ))}
      </div>
    </div>
  );
}
