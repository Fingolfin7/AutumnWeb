import WordCloud from "wordcloud";
import { emberColor } from "./data";
import type { WordRow } from "./payloads";

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

/* Warmer for more frequent words: hue 200 (blue) down to 40 (orange). */
export function wordColor(weight: number, maxWeight: number): string {
  return emberColor(weight, maxWeight);
}

export function drawWordcloud(canvas: HTMLCanvasElement, rows: WordRow[], width: number, height: number) {
  const words = toWordList(rows);
  if (!words.length) return;
  canvas.width = width;
  canvas.height = height;
  const maxWeight = words[0]![1];
  WordCloud(canvas, {
    list: words,
    gridSize: Math.max(8, Math.round(16 * width / 1024)),
    weightFactor: fontSizer(words, width),
    fontFamily: "Manrope, system-ui, sans-serif",
    color: (_word, weight) => wordColor(weight, maxWeight),
    rotateRatio: 0,
    rotationSteps: 2,
    backgroundColor: "transparent",
    drawOutOfBound: false,
    shrinkToFit: true,
  });
}

export function stopWordcloud() {
  WordCloud.stop();
}
