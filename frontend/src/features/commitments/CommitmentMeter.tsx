import type { Commitment } from "@/api/types";
import { formatDuration } from "@/lib/format";
/** The same meter on Review, project rails, Today and advanced editing. */
export function CommitmentMeter({ commitment: c }: { commitment: Commitment }) {
  const { accrued, target, met } = c.current_period;
  const amount = (value: number) => c.commitment_type === "time" ? formatDuration(value) : `${Math.round(value)} session${Math.round(value) === 1 ? "" : "s"}`;
  const percentage = Math.min(100, Math.max(0, accrued / Math.max(target, 1) * 100));
  return <div className={`commitment-meter${c.commitment_type === "time" ? "" : " commitment-meter--count"}`}><div className="commitment-meter-values"><strong>{amount(accrued)}</strong><span>of {amount(target)}</span><span>{accrued > target ? `${amount(accrued - target)} over` : met ? "Target met" : `${amount(Math.max(0,target-accrued))} left`}</span></div><svg className="commitment-meter-track" viewBox="0 0 1000 10" preserveAspectRatio="none" role="img" aria-label={`${c.target.name}: ${amount(accrued)} of ${amount(target)}${met ? ", target met" : ""}`}><rect width="1000" height="10" rx="5" /><rect className={met ? "is-met" : ""} width={percentage * 10} height="10" rx="5" /></svg></div>;
}
