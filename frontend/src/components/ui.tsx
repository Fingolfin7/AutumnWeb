import { useId, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type SelectHTMLAttributes, type ReactNode } from "react";
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
export function SegmentedControl<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void }) {
  const name = useId();
  return <fieldset className="segmented"><legend className="sr-only">{label}</legend>{options.map((option) => <label key={option.value}><input type="radio" name={name} checked={value === option.value} onChange={() => onChange(option.value)} /><span>{option.label}</span></label>)}</fieldset>;
}

/** Date values stay ISO; presets use the account's local day supplied by the caller. */
export function DateInput({ value, onValueChange, today, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & { value: string; onValueChange: (value: string) => void; today: string }) {
  const yesterday = new Date(`${today}T12:00Z`); yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const yesterdayKey = yesterday.toISOString().slice(0,10);
  const outside = (day: string) => props.disabled || !!(props.min && day < String(props.min)) || !!(props.max && day > String(props.max));
  return <div className="date-control"><Input {...props} type="date" value={value} onChange={event => onValueChange(event.target.value)} /><div className="date-presets"><Button variant="quiet" disabled={outside(today)} onClick={() => onValueChange(today)}>Today</Button><Button variant="quiet" disabled={outside(yesterdayKey)} onClick={() => onValueChange(yesterdayKey)}>Yesterday</Button></div></div>;
}
/** One keyboard-accessible file picker with a drop target; browsers keep the native input. */
export function FileDrop({ onFile, hint = "Choose a file or drop it here", ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> & { onFile: (file: File | null) => void; hint?: string }) {
  const [dragging, setDragging] = useState(false);
  return <div className={`file-drop${dragging ? " is-dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); onFile(event.dataTransfer.files[0] ?? null); }}><input {...props} type="file" onChange={event => onFile(event.target.files?.[0] ?? null)} /><span>{hint}</span></div>;
}
