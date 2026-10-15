import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { faBars, faLock, faLockOpen } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "./Icon";
import {
  ALLOCATION_COLORS,
  evenRows,
  isEvenSplit,
  makeRows,
  rowsTotal,
  setRowValue,
  summarize,
  toAllocationWrites,
  toggleLock,
  unallocated,
  type AllocationItem,
  type AllocationRow,
  type AllocationWrite,
} from "@/lib/allocation";

/* The "time split" editor (allocation_editor.js): divides a session across
   the subprojects it was spent on, in whole percents, with sliders, number
   boxes and per-row locks. The maths lives in lib/allocation.ts.

   Props
     items        The currently selected subprojects, {id, name, bp?}. `bp` is
                  the stored allocation in basis points (0 or missing when
                  there is none). The editor renders nothing for fewer than 2
                  items: one subproject always gets the whole session, so
                  callers send `subproject_ids` instead.
     onChange     Called on mount and after every edit with the API-ready
                  allocations ({subproject_id, allocation_bp}, id order, each
                  >= 100bp, total <= 10000bp), or null while fewer than 2
                  items are selected. Safe to put straight into state.
     collapsible  Wear the stop-timer look: a "Time split" header with a
                  one-line summary and mini bar that expands the editor.
                  Default false (always open, as on the edit-session page).
     defaultOpen  Initial state of a collapsible editor. Default false.

   Behaviour: the first set of items starts from their stored `bp`; whenever
   the set of selected ids changes the split resets to even, as the old page
   did on every checkbox change. "Distribute evenly" resets the values and
   releases every lock. A total under 100% is legitimate: the remainder is
   time that belongs to the project but to no subproject. */
export function AllocationEditor({
  items,
  onChange,
  collapsible = false,
  defaultOpen = false,
}: {
  items: AllocationItem[];
  onChange: (allocations: AllocationWrite[] | null) => void;
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const idKey = items
    .map((item) => item.id)
    .sort((a, b) => a - b)
    .join(",");
  const [state, setState] = useState(() => ({ idKey, rows: makeRows(items, false) }));
  const [open, setOpen] = useState(defaultOpen);

  /* The selection changed: start over evenly. Adjusting state while rendering
     is React's sanctioned way to derive state from props without an effect
     round-trip (no flash of stale rows). */
  let rows = state.rows;
  if (state.idKey !== idKey) {
    rows = makeRows(items, true);
    setState({ idKey, rows });
  }

  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  useEffect(() => {
    onChangeRef.current(rows.length >= 2 ? toAllocationWrites(rows) : null);
  }, [rows]);

  const update = (next: AllocationRow[]) => setState({ idKey, rows: next });

  if (rows.length < 2) return null;

  const nameById = new Map(items.map((item) => [item.id, item.name]));
  const allocated = rowsTotal(rows);
  const remainder = unallocated(rows);
  const even = isEvenSplit(rows);

  const className = collapsible ? `attr ${open ? "open" : "collapsed"}` : "attr embedded open";

  return (
    <div className={className}>
      {collapsible ? (
        <button type="button" className="attr-head" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          <span className="attr-chevron">&#9654;</span>
          <span className="attr-head-label">Time split</span>
          <span className="attr-head-summary">{summarize(rows)}</span>
          <span className="attr-head-bar">
            <SegmentBar rows={rows} mini />
          </span>
        </button>
      ) : null}
      <div className="attr-body">
        <div className="attr-bar-top">
          <span className={`attr-state-tag${even ? "" : " custom"}`}>
            <span className="dot" />
            <span>{even ? "Even split" : "Custom split"}</span>
          </span>
          <span className="attr-actions">
            <button type="button" className="attr-mini-btn" onClick={() => update(evenRows(rows))}>
              <Icon icon={faBars} /> Distribute evenly
            </button>
          </span>
        </div>
        <div className="attr-rows">
          {rows.map((row, index) => (
            <AllocationRowView
              key={row.id}
              row={row}
              name={nameById.get(row.id) ?? row.name}
              color={ALLOCATION_COLORS[index % ALLOCATION_COLORS.length]!}
              onValue={(value) => update(setRowValue(rows, index, value))}
              onLock={() => update(toggleLock(rows, index))}
            />
          ))}
        </div>
        <SegmentBar rows={rows} />
        <div className="attr-foot">
          <span className="total">
            Total <b>{allocated}</b>%
          </span>
          <span className={`rem-note${remainder ? "" : " zero"}`} aria-live="polite">
            {remainder ? `${remainder}% unallocated (no subproject)` : "Fully allocated"}
          </span>
        </div>
      </div>
    </div>
  );
}

function SegmentBar({ rows, mini = false }: { rows: AllocationRow[]; mini?: boolean }) {
  const remainder = unallocated(rows);
  return (
    <span className={`attr-segbar${mini ? " mini" : ""}`}>
      {rows.map((row, index) =>
        row.value > 0 ? (
          <span
            key={row.id}
            className="attr-seg"
            style={{ width: `${row.value}%`, background: ALLOCATION_COLORS[index % ALLOCATION_COLORS.length] }}
          />
        ) : null,
      )}
      {remainder ? <span className="attr-seg remainder" style={{ width: `${remainder}%` }} /> : null}
    </span>
  );
}

function AllocationRowView({
  row,
  name,
  color,
  onValue,
  onLock,
}: {
  row: AllocationRow;
  name: string;
  color: string;
  onValue: (value: number) => void;
  onLock: () => void;
}) {
  /* The number box keeps what is being typed until Enter/blur (the old page
     applied it on `change`), so "5" on the way to "50" doesn't rebalance the
     other rows twice. */
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    if (draft !== null) onValue(Number(draft));
    setDraft(null);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      const base = draft !== null ? Number(draft) || row.value : row.value;
      const next = base + (event.key === "ArrowUp" ? 1 : -1);
      setDraft(null);
      onValue(next);
    }
  };

  const sliderStyle: CSSProperties = {
    background: `linear-gradient(90deg, ${color} ${row.value}%, var(--raised-2) ${row.value}%)`,
  };

  return (
    <div className={`attr-row${row.locked ? " locked" : ""}`}>
      <span className="attr-name" title={name}>
        {name}
      </span>
      <input
        type="range"
        className="attr-slider"
        min={1}
        max={100}
        step={1}
        value={row.value}
        disabled={row.locked}
        style={sliderStyle}
        aria-label={`${name} share`}
        onChange={(event) => onValue(Number(event.target.value))}
      />
      <span className="attr-num">
        <input
          type="number"
          min={1}
          max={100}
          step={1}
          value={draft ?? row.value}
          disabled={row.locked}
          aria-label={`${name} percent`}
          onFocus={(event) => event.target.select()}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={onKeyDown}
        />
        <span className="pct">%</span>
      </span>
      <button
        type="button"
        className="attr-lock"
        aria-pressed={row.locked}
        aria-label={`${row.locked ? "Unlock" : "Lock"} ${name}`}
        title={row.locked ? "Unlock this value" : "Lock this value"}
        onClick={onLock}
      >
        <Icon icon={row.locked ? faLock : faLockOpen} />
      </button>
    </div>
  );
}
