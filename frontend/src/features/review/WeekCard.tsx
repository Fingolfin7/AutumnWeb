import { useState } from "react";
import { Sheet } from "@/components/Sheet";
import { useToast } from "@/app/toasts";
import { formatDuration, formatDate } from "@/lib/format";
import type { TallyRow } from "@/features/charts/payloads";
import type { Period } from "./periods";

export function WeekCard({ open, onClose, period, minutes, rows }: { open: boolean; onClose: () => void; period: Period; minutes: number; rows: TallyRow[] }) {
  const [showTotal, setShowTotal] = useState(true);
  const [showProjects, setShowProjects] = useState(false);
  const toast = useToast();
  const range = `${formatDate(period.start)} – ${formatDate(period.end, true)}`;
  const save = async () => {
    await document.fonts.ready;
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 650 + (showProjects ? rows.length * 70 : 0);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const font = css.getPropertyValue("--font-display");
    ctx.fillStyle = color("--surface-0"); ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = color("--brand"); ctx.font = `600 32px ${font}`; ctx.fillText("Autumn / Time well remembered", 90, 100);
    ctx.fillStyle = color("--ink"); ctx.font = `600 42px ${font}`; ctx.fillText(range, 90, 200);
    if (showTotal) { ctx.fillStyle = color("--duration"); ctx.font = `600 120px ${font}`; ctx.fillText(formatDuration(minutes), 90, 390); }
    if (showProjects) rows.forEach((row, index) => {
      ctx.font = `500 30px ${font}`; ctx.fillStyle = color("--project");
      let name = row.name;
      while (ctx.measureText(name).width > 720 && name.length > 1) name = name.slice(0, -2) + "…";
      ctx.fillText(name, 90, 510 + index * 70);
      ctx.fillStyle = color("--duration"); ctx.textAlign = "right"; ctx.fillText(formatDuration(row.total_time), 1110, 510 + index * 70); ctx.textAlign = "left";
    });
    canvas.toBlob((blob) => {
      if (!blob) { toast.error("The image could not be created. Try again."); return; }
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = `autumn-${period.start}.png`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "image/png");
  };
  return <Sheet open={open} onClose={onClose} title="Save a review card">
    <div className="fields">
      <p className="muted">Choose what appears in the image. Notes and account details are never included.</p>
      <label className="check-row"><input type="checkbox" checked={showTotal} onChange={(event) => setShowTotal(event.target.checked)} /> Total time</label>
      <label className="check-row"><input type="checkbox" checked={showProjects} onChange={(event) => setShowProjects(event.target.checked)} /> Project names and time</label>
      <div className="review-card-preview"><span>Autumn</span><h3>{range}</h3>{showTotal ? <strong>{formatDuration(minutes)}</strong> : null}{showProjects ? rows.map((row) => <p key={row.name}><span>{row.name}</span> <b>{formatDuration(row.total_time)}</b></p>) : null}</div>
      <button className="btn btn--primary" type="button" onClick={() => void save()}>Save image</button>
    </div>
  </Sheet>;
}
