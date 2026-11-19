import { useId, useState, type InputHTMLAttributes } from "react";

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

/** One full-width file action; drag-and-drop remains a desktop shortcut. */
export function FileDrop({ onFile, hint, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> & { onFile: (file: File | null) => void; hint?: string }) {
  const [dragging, setDragging] = useState(false);
  const [name, setName] = useState("");
  const pick = (file: File | null) => { setName(file?.name ?? ""); onFile(file); };
  return <div className={`file-drop${dragging ? " is-dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!props.disabled) pick(event.dataTransfer.files[0] ?? null); }}><input {...props} type="file" onChange={event => pick(event.target.files?.[0] ?? null)} /><span className="file-drop-action">{name || "Choose file"}</span>{!name && hint ? <span className="file-drop-name">{hint}</span> : null}</div>;
}
