declare module "wordcloud" {
  interface WordCloudOptions {
    list: [string, number][];
    gridSize?: number;
    weightFactor?: number | ((weight: number) => number);
    fontFamily?: string;
    color?: string | ((word: string, weight: number) => string);
    rotateRatio?: number;
    rotationSteps?: number;
    backgroundColor?: string;
    drawOutOfBound?: boolean;
    shrinkToFit?: boolean;
    click?: (item: [string, number]) => void;
  }
  function WordCloud(element: HTMLCanvasElement | HTMLElement, options: WordCloudOptions): void;
  namespace WordCloud {
    function stop(): void;
  }
  export default WordCloud;
}
