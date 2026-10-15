import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { countAt, fixed2, loosenTo, position, sameCutoff, snap, type SimilarityScale } from "./similarity";

/* Arrow keys fire a change per press: wait until they settle. */
const COMMIT_DELAY_MS = 450;

type Props = {
  /** The cutoff in use. */
  value: number;
  /** The marked tick: the account's cutoff. */
  defaultValue: number;
  defaultLabel?: string;
  scale: SimilarityScale;
  /** Called once the slider settles on a new value. */
  onCommit: (value: number) => void;
  /** Related matches kept at each step, floor to ceiling (page mode). */
  counts?: readonly number[] | null;
  /** The closest related match's score, down to the floor. */
  best?: number | null;
  /** Page mode: fold into its readout row unless there is something to do. */
  collapsible?: boolean;
  /** Field mode commits at once (no search to re-run). */
  immediate?: boolean;
  loading?: boolean;
  title?: string;
};

/* The Related slider (core/partials/similarity_slider.html). The native
   range keeps pointer, touch and keyboard handling; the track, fill and
   markers are drawn underneath by the Night Ledger CSS. While dragging, the
   readout shows how many related matches the position would keep, from
   ``counts``, so no request is made until it settles. */
export function SimilaritySlider({
  value,
  defaultValue,
  defaultLabel = "Your default",
  scale,
  onCommit,
  counts,
  best,
  collapsible,
  immediate,
  loading,
  title = "Match closeness",
}: Props) {
  const id = useId();
  const rangeRef = useRef<HTMLInputElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [draft, setDraft] = useState(value);
  const committed = useRef(value);

  useEffect(() => {
    setDraft(value);
    committed.current = value;
  }, [value]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const commit = (next: number) => {
    window.clearTimeout(timer.current);
    if (sameCutoff(next, committed.current)) return;
    const run = () => {
      committed.current = next;
      onCommit(next);
    };
    if (immediate) run();
    else timer.current = window.setTimeout(run, COMMIT_DELAY_MS);
  };
  const commitRef = useRef(commit);
  commitRef.current = commit;
  const scaleRef = useRef(scale);
  scaleRef.current = scale;

  // React's onChange is the input event; the native change fires on release.
  useEffect(() => {
    const range = rangeRef.current;
    if (!range) return;
    const onChange = () => commitRef.current(snap(Number(range.value), scaleRef.current));
    range.addEventListener("change", onChange);
    return () => range.removeEventListener("change", onChange);
  }, []);

  const jump = (target: number) => {
    const next = snap(target, scale);
    setDraft(next);
    commit(next);
  };

  const count = countAt(counts, draft, scale);
  const hasCounts = counts != null;
  const appliedCount = countAt(counts, value, scale) ?? 0;
  const style = { "--fill": position(draft, scale).toFixed(2) } as CSSProperties;
  const at = (cutoff: number) => ({ "--at": String(position(cutoff, scale)) }) as CSSProperties;
  const defaultInRange = defaultValue >= scale.floor && defaultValue <= scale.ceiling;
  const looser = loosenTo(best, draft, scale);
  const open = hasCounts && (appliedCount === 0 || !sameCutoff(value, defaultValue));

  const head = (
    <>
      <span className="similarity-title" id={`${id}-title`}>
        {title}
      </span>
      <output className="similarity-readout" htmlFor={id} aria-live="polite">
        <b>{fixed2(draft)}</b>
        {count !== null ? <> · {count} related</> : null}
      </output>
      {collapsible ? <Icon icon={faChevronDown} className="similarity-chevron" /> : null}
    </>
  );

  const body = (
    <>
      <div className="similarity-slider">
        {scale.marks.map((mark) => (
          <span
            key={mark.label}
            className={`similarity-mark${mark.value <= draft + 1e-9 ? " is-passed" : ""}`}
            style={at(mark.value)}
            aria-hidden="true"
          />
        ))}
        {defaultInRange ? (
          <span
            className="similarity-default"
            style={at(defaultValue)}
            title={`${defaultLabel}, ${fixed2(defaultValue)}`}
            aria-hidden="true"
          />
        ) : null}
        <input
          ref={rangeRef}
          type="range"
          className="similarity-range"
          id={id}
          min={fixed2(scale.floor)}
          max={fixed2(scale.ceiling)}
          step={fixed2(scale.step)}
          value={fixed2(draft)}
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-help`}
          aria-valuetext={`${fixed2(draft)}${count !== null ? `, ${count} related` : ""}`}
          onChange={(event) => setDraft(snap(Number(event.target.value), scale))}
        />
      </div>
      <div className="similarity-labels" aria-hidden="true">
        {scale.marks.map((mark) => (
          <button
            key={mark.label}
            type="button"
            tabIndex={-1}
            style={at(mark.value)}
            className={sameCutoff(mark.value, draft) ? "is-current" : undefined}
            onClick={() => jump(mark.value)}
          >
            {mark.label}
          </button>
        ))}
      </div>
      <p className="sr-only" id={`${id}-help`}>
        Lower is looser: more matches count as related. Higher is stricter.
      </p>
      {hasCounts && count === 0 ? (
        <p className="similarity-hint">
          {looser !== null && best != null ? (
            <>
              <span>
                Nothing related at <b>{fixed2(draft)}</b>. The closest match is <b>{fixed2(looser)}</b>.
              </span>
              <button type="button" className="btn btn--ghost" onClick={() => jump(looser)}>
                Loosen to {fixed2(looser)}
              </button>
            </>
          ) : (
            <span>Nothing related, even at the loosest setting.</span>
          )}
        </p>
      ) : null}
    </>
  );

  const classes = ["similarity", collapsible ? "similarity--collapsible" : "", loading ? "is-loading" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} style={style}>
      {collapsible ? (
        <details className="similarity-disclosure" open={open || undefined}>
          <summary className="similarity-head">{head}</summary>
          {body}
        </details>
      ) : (
        <>
          <div className="similarity-head">{head}</div>
          {body}
        </>
      )}
    </div>
  );
}
