import WordCloud from "wordcloud";
import type { WordRow } from "./payloads";
import { token } from "./theme";

/* Word cloud of session notes (core/static/core/js/charts/wordcloud.js).
   Not a Chart.js chart: it paints straight onto the canvas. */

export function toWordList(rows: WordRow[]): [string, number][] {
  return rows.map((row) => [row.text, Number(row.weight)]);
}

/* Normalise frequencies into bounded font sizes. Multiplying raw counts made
   uniformly frequent words hundreds of pixels tall, so WordCloud could fail
   to place any of them and leave a blank canvas. */
export function fontSizer(words: [string, number][], canvasWidth: number): (weight: number) => number {
  const largest = words[0]![1];
  const smallest = words[words.length - 1]![1];
  const range = largest - smallest;
  const max = Math.min(72, Math.max(36, canvasWidth / 10));
  const min = Math.max(12, max / 4);
  return (weight) => (range ? min + ((weight - smallest) / range) * (max - min) : max);
}

/* Three tiers by frequency: the accent for the words that dominate, note
   ochre for the middle, quiet ink for the rest. */
export function wordColor(weight: number, maxWeight: number): string {
  const share = weight / maxWeight;
  return token(share > 0.6 ? "--brand" : share > 0.3 ? "--note" : "--ink-2");
}

export function drawWordcloud(canvas: HTMLCanvasElement, rows: WordRow[], width: number, height: number) {
  const words = toWordList(rows);
  if (!words.length) return;
  canvas.width = width;
  canvas.height = height;
  const maxWeight = words[0]![1];
  WordCloud(canvas, {
    list: words,
    gridSize: Math.round(((words.length > 50 ? 8 : 16) * width) / 1024),
    weightFactor: fontSizer(words, width),
    fontFamily: token("--font-ui"),
    fontWeight: "600",
    color: (_word, weight) => wordColor(weight, maxWeight),
    rotateRatio: 0.4,
    rotationSteps: 2,
    backgroundColor: "transparent",
    drawOutOfBound: false,
    shrinkToFit: true,
  });
}

export function stopWordcloud() {
  WordCloud.stop();
}
