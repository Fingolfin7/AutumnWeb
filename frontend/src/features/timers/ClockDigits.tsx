/** Stable cells also protect clocks when a fallback font lacks tabular figures. */
export function ClockDigits({ value }: { value: string }) {
  return <span className="clock-digits">{[...value].map((digit, index) => <span className={digit === ":" ? "clock-colon" : "clock-digit"} key={index}>{digit}</span>)}</span>;
}
