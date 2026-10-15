import { useId, useMemo, useState } from "react";
import { faSearch, type IconDefinition } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "./Icon";

export interface PickerOption {
  id: number;
  label: string;
  /** Optional CSS colour, e.g. a tag colour. */
  color?: string | null;
}

/* The one shape every multi-select filter wears (partials/option_picker.html
   + option_pickers.js): a bounded well of chips, an optional search field,
   checked chips pinned to the front so a selection never scrolls out of
   sight, and an "N selected" button that clears it. With `mode`, the same
   ticks read as "only these" or "everything but these". */
export function OptionPicker({
  label,
  icon,
  iconClass,
  options,
  selected,
  onChange,
  searchPlaceholder,
  emptyText = "Nothing matches that search.",
  mode,
  onModeChange,
  modeLabels = { exclude: "Exclude", include: "Only these" },
}: {
  label: string;
  icon?: IconDefinition;
  iconClass?: string;
  options: PickerOption[];
  selected: number[];
  onChange: (ids: number[]) => void;
  searchPlaceholder?: string;
  emptyText?: string;
  mode?: "include" | "exclude";
  onModeChange?: (mode: "include" | "exclude") => void;
  modeLabels?: { include: string; exclude: string };
}) {
  const [query, setQuery] = useState("");
  const labelId = useId();
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = needle ? options.filter((o) => o.label.toLowerCase().includes(needle) || selectedSet.has(o.id)) : options;
    return [...matching.filter((o) => selectedSet.has(o.id)), ...matching.filter((o) => !selectedSet.has(o.id))];
  }, [options, query, selectedSet]);

  const toggle = (id: number) => {
    onChange(selectedSet.has(id) ? selected.filter((value) => value !== id) : [...selected, id]);
  };

  return (
    <div className="field" role="group" aria-labelledby={labelId}>
      <div className="field-head">
        <span className="field-label" id={labelId}>
          {icon ? <Icon icon={icon} className={iconClass} /> : null} {label}
        </span>
        <span className="picker-head-controls">
          {mode && onModeChange ? (
            <span className="picker-mode" role="group" aria-label="How this list is applied">
              {(["exclude", "include"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`picker-mode-btn${mode === value ? " is-active" : ""}`}
                  data-picker-mode={value}
                  aria-pressed={mode === value}
                  onClick={() => onModeChange(value)}
                >
                  {modeLabels[value]}
                </button>
              ))}
            </span>
          ) : null}
          {selected.length ? (
            <button type="button" className="picker-count" onClick={() => onChange([])} title="Clear selection">
              {selected.length} selected ×
            </button>
          ) : null}
        </span>
      </div>
      <div className="picker">
        {searchPlaceholder ? (
          <div className="picker-search">
            <Icon icon={faSearch} />
            <input
              type="text"
              className="picker-search-input"
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              autoComplete="off"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        ) : null}
        <div className="picker-options">
          {visible.map((option) => (
            <label key={option.id} className="option-chip" style={option.color ? ({ "--tag": option.color } as React.CSSProperties) : undefined}>
              <input type="checkbox" checked={selectedSet.has(option.id)} onChange={() => toggle(option.id)} />
              <span className="option-label tag-label">{option.label}</span>
            </label>
          ))}
        </div>
        {visible.length === 0 ? <p className="picker-empty">{emptyText}</p> : null}
      </div>
    </div>
  );
}
