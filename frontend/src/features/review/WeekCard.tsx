import { useState } from "react";
import { Sheet } from "@/components/Sheet";
import { useToast } from "@/app/toasts";
import { formatDuration, formatDate } from "@/lib/format";
import { addDays } from "@/features/notifications/dates";
import type { DailyTotalRow, TallyRow } from "@/features/charts/payloads";
import { periodDays, type Period } from "./periods";

export function WeekCard({ open, onClose, period, minutes, rows, daily }: { open: boolean; onClose: () => void; period: Period; minutes: number; rows: TallyRow[]; daily: DailyTotalRow[] }) {
  const [showTotal, setShowTotal] = useState(true);
  const [showProjects, setShowProjects] = useState(false);
  const toast = useToast();
  const range = `${formatDate(period.start)} – ${formatDate(period.end, true)}`;
  const days = Array.from({ length: Math.min(periodDays(period), 366) }, (_, index) => {
    const date = addDays(period.start, index);
    return { date, hours: Number(daily.find((row) => row.date === date)?.hours ?? 0) };
  });
  const active = days.filter((day) => day.hours > 0).length;
  const level = (hours: number) => hours === 0 ? 0 : hours < 1 ? 1 : hours < 2 ? 2 : hours < 4 ? 3 : 4;
  const save = async () => {
    await document.fonts.ready;
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 800 + Math.ceil(days.length / 28) * 28 + (showProjects ? rows.length * 80 : 0);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const font = css.getPropertyValue("--font-display");
    ctx.fillStyle = color("--surface-0"); ctx.fillRect(0, 0, canvas.width, canvas.height);
    const glow = ctx.createRadialGradient(970, 150, 0, 970, 150, 700);
    glow.addColorStop(0, "rgba(233,163,91,.22)"); glow.addColorStop(1, "rgba(233,163,91,0)");
    ctx.fillStyle = glow; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = color("--brand"); ctx.font = `600 30px ${font}`; ctx.fillText("Autumn", 90, 100);
    ctx.fillStyle = color("--ink"); ctx.font = `500 40px ${font}`; ctx.fillText(range, 90, 200);
    if (showTotal) { ctx.fillStyle = color("--duration"); ctx.font = `600 120px ${font}`; ctx.fillText(formatDuration(minutes), 90, 365); }
    ctx.fillStyle = color("--ink-2"); ctx.font = `400 28px ${font}`; ctx.fillText(`${active} ${active === 1 ? "day" : "days"} with time remembered`, 90, 440);
    const colors = ["--surface-2", "--brand-deep", "--brand", "--brand-hover", "--note"];
    days.forEach((day, index) => {
      ctx.fillStyle = color(colors[level(day.hours)]!);
      ctx.beginPath(); ctx.roundRect(90 + (index % 28) * 35, 500 + Math.floor(index / 28) * 28, 23, 18, 5); ctx.fill();
    });
    const ledgerY = 590 + Math.ceil(days.length / 28) * 28;
    if (showProjects) rows.forEach((row, index) => {
      ctx.font = `500 28px ${font}`; ctx.fillStyle = color("--project");
      let name = row.name;
      while (ctx.measureText(name).width > 750 && name.length > 1) name = name.slice(0, -2) + "…";
      ctx.fillText(name, 90, ledgerY + index * 80);
      ctx.fillStyle = color("--duration"); ctx.textAlign = "right"; ctx.fillText(formatDuration(row.total_time), 1110, ledgerY + index * 80); ctx.textAlign = "left";
    });
    ctx.strokeStyle = color("--brand-deep"); ctx.beginPath(); ctx.moveTo(90, canvas.height - 125); ctx.lineTo(1110, canvas.height - 125); ctx.stroke();
    ctx.fillStyle = color("--muted"); ctx.font = `400 25px ${font}`; ctx.fillText("A little light left by the things you did.", 90, canvas.height - 70);
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
      <div className="review-card-preview"><span className="review-card-brand">Autumn</span><h3>{range}</h3>{showTotal ? <strong>{formatDuration(minutes)}</strong> : null}<p className="review-card-days">{active} {active === 1 ? "day" : "days"} with time remembered</p><div className="review-card-embers" aria-label={`${active} active days in this period`}>{days.map((day) => <span key={day.date} className={`card-ember card-ember--${level(day.hours)}`} title={`${formatDate(day.date)}: ${formatDuration(day.hours * 60)}`} />)}</div>{showProjects ? rows.map((row) => <p className="review-card-project" key={row.name}><span>{row.name}</span><b>{formatDuration(row.total_time)}</b></p>) : null}<footer>A little light left by the things you did.</footer></div>
      <div className="review-card-actions"><button className="btn btn--primary" type="button" onClick={() => void save()}>Save image</button></div>
    </div>
  </Sheet>;
}
