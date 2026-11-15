/* Chart colours are the Night Ledger tokens (focus_desk.css :root), read from
   the page so a token change reaches the charts. The fallbacks are the same
   values, for tests and for a canvas drawn before the stylesheet applies. */
const FALLBACK = {
  "--ink": "#e4e8e5",
  "--ink-2": "#b9c1bc",
  "--muted": "#8b948f",
  "--ink-invert": "#101214",
  "--slab-solid": "#15181b",
  "--hairline": "rgba(228, 232, 229, 0.085)",
  "--hairline-2": "rgba(228, 232, 229, 0.16)",
  "--raised-2": "rgba(255, 255, 255, 0.075)",
  "--font-ui": '"Aptos", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
  "--brand": "#d18b4c",
  "--time": "#58b1a3",
  "--project": "#d0796f",
  "--note": "#c6b276",
  "--sub": "#8aabce",
  "--duration": "#8dbc75",
  "--magenta": "#9b83a7",
};
export type Token = keyof typeof FALLBACK;

const read = new Map<Token, string>();
export function token(name: Token): string {
  let value = read.get(name);
  if (value === undefined) {
    value = (typeof document !== "undefined" && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || FALLBACK[name];
    read.set(name, value);
  }
  return value;
}

/* Series hues, in a fixed order: the app's semantic hues, ordered so
   neighbours stay apart for colour-blind readers (checked with an OKLab
   CVD simulation; the closest neighbours are told apart by the legend and
   the 2px gaps too). Past seven, darker earth tones that sit with them. */
const SERIES: Token[] = ["--brand", "--time", "--project", "--note", "--sub", "--duration", "--magenta"];
const EXTRA = ["#a87854", "#66837f", "#8c7656", "#6f8465", "#596d80"];

export function seriesColor(index: number): string {
  const all = SERIES.length + EXTRA.length;
  const i = index % all;
  return i < SERIES.length ? token(SERIES[i]!) : EXTRA[i - SERIES.length]!;
}
