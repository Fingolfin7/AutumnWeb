import { faCheck, faFire, faHourglassHalf, faTimes } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import type { DashboardCommitment } from "./api";

/** Historical streaks live in the shared commitment's Balance & details. */
export function CommitmentHistory({ item }: { item: DashboardCommitment }) {
  const { streak } = item;
  return (
      <div className="streak-row">
        <Icon icon={faFire} className={`streak-flame${streak.current_streak ? " is-hot" : ""}`} />
        <span className="streak-count">
          {streak.current_streak} period{streak.current_streak === 1 ? "" : "s"}
        </span>
        <div className="period-strip">
          {streak.periods.map((period) => {
            const state = period.is_current ? "current" : period.saved_by_bank ? "banked" : period.met ? "met" : "missed";
            const title = `${Math.round(period.actual)}/${period.target}${
              period.saved_by_bank ? " (bank covered deficit)" : period.is_current ? " — current period" : ""
            }`;
            return (
              <span key={period.period_start} className={`period-cell ${state}`} title={title}>
                <Icon icon={period.is_current ? faHourglassHalf : period.met ? faCheck : faTimes} />
              </span>
            );
          })}
        </div>
      </div>
  );
}
