import { useEffect, useState } from "react";
import { formatDuration } from "@/lib/format";

/** Minutes on the wire, familiar hours and minutes while editing. Plain numbers remain minutes. */
export function parseTimeTarget(text: string): string {
  if (/^\d+$/.test(text.trim())) return text.trim();
  const match = /^\s*(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?$/i.exec(text);
  return match && (match[1] || match[2]) ? String(Number(match[1] ?? 0) * 60 + Number(match[2] ?? 0)) : "";
}
export function TargetInput({ id, value, onChange, time, invalid }: { id: string; value: string; onChange: (value: string) => void; time: boolean; invalid?: boolean }) {
  const display = (amount: string) => time && amount ? formatDuration(Number(amount)) : amount;
  const [text, setText] = useState(() => display(value));
  useEffect(() => { if (value !== (time ? parseTimeTarget(text) : text)) setText(display(value)); }, [value, time]); // Preserve incomplete typing; external resets still update.
  return <input className="input" id={id} type={time ? "text" : "number"} inputMode={time ? "text" : "numeric"} min={time ? undefined : 1} step={time ? undefined : 1} required value={text} placeholder={time ? "3h 30m" : "Session count"} aria-invalid={invalid} aria-describedby={`${id}-help`} onChange={(event) => { setText(event.target.value); onChange(time ? parseTimeTarget(event.target.value) : event.target.value); }} />;
}
