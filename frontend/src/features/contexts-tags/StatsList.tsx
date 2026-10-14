import { formatMinutesFull, formatStatusCounts, type ProjectSummary } from "./stats";

/* The sidebar's projects / total time / average session rows. */
export function StatsList({ summary }: { summary: ProjectSummary }) {
  const counts = formatStatusCounts(summary.statusCounts);
  return (
    <div className="meta-list">
      <div className="meta-row">
        <span className="meta-label">Projects</span>
        <span className="meta-value">
          {summary.total} {counts}
        </span>
      </div>
      <div className="meta-row">
        <span className="meta-label">Total time</span>
        <span className="meta-value text-green">{formatMinutesFull(summary.totalMinutes)}</span>
      </div>
      <div className="meta-row">
        <span className="meta-label">Average session</span>
        <span className="meta-value text-green">{formatMinutesFull(summary.averageMinutes)}</span>
      </div>
    </div>
  );
}
