import { useSearchParams } from "react-router";
import { SimilaritySlider } from "./SimilaritySlider";
import { summaryScale, type RelatedSummary } from "./api";
import { similarityParam } from "./similarity";

/* The page-mode Related slider (Sessions, Projects): folded into its readout
   unless nothing is related or the cutoff is not the default. Settling on a
   value re-runs the search with ?similarity=, left out at the default. */
export function RelatedSlider({ summary, loading }: { summary: RelatedSummary; loading?: boolean }) {
  const [params, setParams] = useSearchParams();
  const commit = (value: number) => {
    const next = new URLSearchParams(params);
    const param = similarityParam(value, summary.default);
    if (param === null) next.delete("similarity");
    else next.set("similarity", param);
    setParams(next);
  };
  return (
    <SimilaritySlider
      collapsible
      value={summary.similarity}
      defaultValue={summary.default}
      scale={summaryScale(summary)}
      counts={summary.counts}
      best={summary.best}
      loading={loading}
      onCommit={commit}
    />
  );
}
