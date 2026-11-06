import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type SelectHTMLAttributes, type ReactNode } from "react";
import { faCalendarAlt, faClock, faChevronLeft, faChevronRight } from "@fortawesome/free-solid-svg-icons";
import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "./Icon";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "quiet" | "destructive" };
/** One primary action per view. Secondary for alternatives; quiet for utilities. */
export function Button({ variant = "secondary", className = "", type = "button", ...props }: ButtonProps) {
  return <button type={type} className={`btn btn--${variant === "destructive" ? "danger" : variant} ${className}`} {...props} />;
}

export function IconButton({ icon, label, className = "", ...props }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & { icon: IconDefinition; label: string }) {
  return <button type="button" className={`btn-icon ${className}`} aria-label={label} title={label} {...props}><Icon icon={icon} /></button>;
}

export function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`chip ${className}`}>{children}</span>;
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  if (props.type === "time") return <TimeInput {...props} className={className} />;
  return <input className={`input ${className}`} {...props} />;
}

export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`select ${className}`} {...props} />;
}

/** Native checkbox semantics and keyboard behavior, with a switch-shaped track. */
export function Toggle({ label, id, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: string }) {
  const generated = useId();
  return <label className="toggle" htmlFor={id ?? generated}><input {...props} id={id ?? generated} type="checkbox" role="switch" /><span>{label}</span></label>;
}

/** A native radio group: Tab enters, arrow keys select. Values must be unique. */
export function SegmentedControl<T extends string>({ label, value, options, onChange, onReselect }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void; onReselect?: (value: T) => void }) {
  const name = useId();
  const group = useRef<HTMLFieldSetElement>(null);
  useEffect(() => {
    const container = group.current;
    const selected = container?.querySelector<HTMLInputElement>("input:checked")?.parentElement;
    if (!container || !selected || container.scrollWidth <= container.clientWidth) return;
    const left = selected.getBoundingClientRect().left - container.getBoundingClientRect().left + container.scrollLeft;
    const right = left + selected.getBoundingClientRect().width;
    if (left < container.scrollLeft) container.scrollLeft = left;
    else if (right > container.scrollLeft + container.clientWidth) container.scrollLeft = right - container.clientWidth;
  }, [value]);
  return <fieldset ref={group} className="segmented"><legend className="sr-only">{label}</legend>{options.map((option) => <label key={option.value}><input type="radio" name={name} checked={value === option.value} onClick={() => { if (value === option.value) onReselect?.(option.value); }} onChange={() => onChange(option.value)} /><span>{option.label}</span></label>)}</fieldset>;
}

function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); ref.current?.querySelector<HTMLButtonElement>(".temporal-trigger")?.focus(); } };
    document.addEventListener("pointerdown", close);
    ref.current?.addEventListener("keydown", escape);
    const element = ref.current;
    return () => { document.removeEventListener("pointerdown", close); element?.removeEventListener("keydown", escape); };
  }, [open]);
  return { open, setOpen, ref };
}

/** ISO input and a Monday-first calendar. Presets live in the calendar, not below every field. */
export function DateInput({ value, onValueChange, today, presets = "past", ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & { value: string; onValueChange: (value: string) => void; today: string; presets?: "past" | "future" | "none" }) {
  const { open, setOpen, ref } = usePopover();
  const [month, setMonth] = useState((value || today).slice(0, 7));
  useEffect(() => {
    if (open) ref.current?.querySelector(".temporal-popover")?.scrollIntoView?.({ block: "nearest" });
  }, [open, ref]);
  const shift = (amount: number) => { const date = new Date(`${month}-01T12:00Z`); date.setUTCMonth(date.getUTCMonth() + amount); setMonth(date.toISOString().slice(0, 7)); };
  const first = new Date(`${month}-01T12:00Z`);
  const offset = (first.getUTCDay() + 6) % 7;
  const days = new Date(first.getUTCFullYear(), first.getUTCMonth() + 1, 0).getDate();
  const nextWeek = new Date(`${today}T12:00Z`); nextWeek.setUTCDate(nextWeek.getUTCDate() + 7);
  const nearby = new Date(`${today}T12:00Z`); nearby.setUTCDate(nearby.getUTCDate() + (presets === "future" ? 1 : -1));
  const outside = (day: string) => props.disabled || !!(props.min && day < String(props.min)) || !!(props.max && day > String(props.max));
  const choose = (day: string) => { onValueChange(day); setOpen(false); ref.current?.querySelector<HTMLInputElement>("input")?.focus(); };
  return <div className="date-control temporal-control" ref={ref}><input {...props} className={`input ${props.className ?? ""}`} type="date" value={value} onChange={event => onValueChange(event.target.value)} /><button className="temporal-trigger btn-icon" type="button" aria-label={`Choose ${props["aria-label"] ?? "date"}`} aria-expanded={open} disabled={props.disabled} onClick={() => { setMonth((value || today).slice(0, 7)); setOpen(!open); }}><Icon icon={faCalendarAlt} /></button>{open ? <div className="temporal-popover" role="group" aria-label="Calendar"><div className="calendar-heading"><IconButton icon={faChevronLeft} label="Previous month" onClick={() => shift(-1)} /><strong>{first.toLocaleDateString("en", { month: "long", year: "numeric", timeZone: "UTC" })}</strong><IconButton icon={faChevronRight} label="Next month" onClick={() => shift(1)} /></div><div className="calendar-days">{["M", "T", "W", "T", "F", "S", "S"].map((label, index) => <span key={index} aria-hidden="true">{label}</span>)}{Array.from({ length: offset }, (_, index) => <span key={`blank-${index}`} />)}{Array.from({ length: days }, (_, index) => { const day = `${month}-${String(index + 1).padStart(2, "0")}`; return <button type="button" key={day} disabled={outside(day)} aria-label={new Date(`${day}T12:00Z`).toLocaleDateString("en", { dateStyle: "full", timeZone: "UTC" })} aria-pressed={day === value} onClick={() => choose(day)}>{index + 1}</button>; })}</div>{presets !== "none" ? <div className="date-presets"><Button variant="quiet" disabled={outside(today)} onClick={() => choose(today)}>Today</Button><Button variant="quiet" disabled={outside(nearby.toISOString().slice(0, 10))} onClick={() => choose(nearby.toISOString().slice(0, 10))}>{presets === "future" ? "Tomorrow" : "Yesterday"}</Button>{presets === "future" ? <Button variant="quiet" disabled={outside(nextWeek.toISOString().slice(0, 10))} onClick={() => choose(nextWeek.toISOString().slice(0, 10))}>Next week</Button> : null}</div> : null}</div> : null}</div>;
}

function TimeInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const { open, setOpen, ref } = usePopover();
  const value = String(props.value ?? "").slice(0, 5);
  const change = (next: string) => {
    const input = ref.current?.querySelector("input");
    if (!input) return;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const hour = value.slice(0, 2) || "09";
  const minute = value.slice(3, 5) || "00";
  return <div className="temporal-control time-control" ref={ref}>
    <input {...props} type="time" step={60} value={value} className={`input ${className}`} />
    <button type="button" className="temporal-trigger btn-icon" aria-label="Choose time" disabled={props.disabled} aria-expanded={open} onClick={() => setOpen(!open)}><Icon icon={faClock} /></button>
    {open ? <div className="time-chips" role="group" aria-label="Time">
      <fieldset><legend>Hour</legend><div>{Array.from({ length: 24 }, (_, index) => { const next = String(index).padStart(2, "0"); return <button type="button" key={next} aria-pressed={hour === next} onClick={() => change(`${next}:${minute}`)}>{next}</button>; })}</div></fieldset>
      <fieldset><legend>Minute</legend><div>{["00", "15", "30", "45"].map(next => <button type="button" key={next} aria-pressed={minute === next} onClick={() => change(`${hour}:${next}`)}>{next}</button>)}</div></fieldset>
      <Button variant="quiet" onClick={() => setOpen(false)}>Done</Button>
    </div> : null}
  </div>;
}

/** One full-width file action; drag-and-drop remains a desktop shortcut. */
export function FileDrop({ onFile, hint, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> & { onFile: (file: File | null) => void; hint?: string }) {
  const [dragging, setDragging] = useState(false);
  const [name, setName] = useState("");
  const pick = (file: File | null) => { setName(file?.name ?? ""); onFile(file); };
  return <div className={`file-drop${dragging ? " is-dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!props.disabled) pick(event.dataTransfer.files[0] ?? null); }}><input {...props} type="file" onChange={event => pick(event.target.files?.[0] ?? null)} /><span className="file-drop-action">{name || "Choose file"}</span>{!name && hint ? <span className="file-drop-name">{hint}</span> : null}</div>;
}
