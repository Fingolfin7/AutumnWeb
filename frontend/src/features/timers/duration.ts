/** Human duration input. Bare numbers mean minutes; stored values stay exact. */
export function parseDuration(text: string): number {
  const value = text.trim().toLowerCase();
  if (/^\d+(?:\.\d+)?$/.test(value)) return Number(value);
  const match = value.match(/^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+(?:\.\d+)?)\s*m?)?$/);
  return match && (match[1] || match[2]) ? Number(match[1] ?? 0) * 60 + Number(match[2] ?? 0) : NaN;
}
