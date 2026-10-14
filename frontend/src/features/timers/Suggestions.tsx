import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  faBullseye,
  faCalendarDay,
  faHistory,
  faLightbulb,
  faPlay,
  faSeedling,
  faSyncAlt,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Disclose } from "@/components/Disclose";
import { api, requestJson, unwrap } from "@/api/client";
import { keys } from "@/api/keys";
import type { components } from "@/api/schema";
import { errorMessage } from "@/api/errors";
import { useToast } from "@/app/toasts";
import { useActiveContext } from "@/app/context";
import { bootstrap } from "@/bootstrap";
import { useStartTimer } from "./api";

type Suggestion = components["schemas"]["TimerSuggestion"];
type Luna = components["schemas"]["LunaRecommendations"];

const LUNA_DEADLINE_MS = 195_000;
const EFFORTS = [
  ["low", "Low effort"],
  ["medium", "Medium effort"],
  ["high", "High effort"],
  ["xhigh", "xHigh effort"],
  ["max", "Max effort"],
] as const;

/* Luna answers 202 while it is still thinking; poll every 5 s up to the old
   195 s budget. */
async function fetchLuna(context: string | undefined, signal: AbortSignal): Promise<Luna> {
  const deadline = Date.now() + LUNA_DEADLINE_MS;
  const url = context ? `/api/v2/recommendations/luna/?context=${encodeURIComponent(context)}` : "/api/v2/recommendations/luna/";
  for (;;) {
    const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" }, signal });
    if (response.status === 202) {
      if (Date.now() + 5000 >= deadline) throw new Error("Luna is still thinking");
      await new Promise((resolve) => window.setTimeout(resolve, 5000));
      continue;
    }
    if (!response.ok) throw new Error(String(response.status));
    return (await response.json()) as Luna;
  }
}

/* The Timers page side panel (timers.html "Suggestions"). */
export function Suggestions() {
  const { contextIdsParam } = useActiveContext();
  const client = useQueryClient();
  const toast = useToast();
  const [effort, setEffort] = useState<string>("xhigh");

  const heuristics = useQuery({
    queryKey: [...keys.recommendations("timers"), contextIdsParam ?? "all"],
    queryFn: () =>
      unwrap(api.GET("/api/v2/recommendations/timers/", { params: { query: contextIdsParam ? { context: contextIdsParam } : {} } })),
    staleTime: 60_000,
  });
  const luna = useQuery({
    queryKey: [...keys.recommendations("luna"), contextIdsParam ?? "all"],
    queryFn: ({ signal }) => fetchLuna(contextIdsParam, signal),
    staleTime: 5 * 60_000,
    retry: false,
  });

  useEffect(() => {
    requestJson<{ luna_recommendation_effort?: string }>("GET", "/api/v2/me/preferences/")
      .then((prefs) => prefs.luna_recommendation_effort && setEffort(prefs.luna_recommendation_effort))
      .catch(() => undefined);
  }, []);

  const refresh = useMutation({
    mutationFn: () => requestJson("POST", "/api/v2/recommendations/luna/refresh/", { luna_effort: effort }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.recommendations("luna") });
      toast.info("Asked Luna for fresh recommendations.");
    },
    onError: (error) => toast.error(`Couldn't refresh: ${errorMessage(error)}`),
  });

  const groups = heuristics.data;
  const hasHeuristics = !!groups && (groups.commitments.length > 0 || groups.habits.length > 0 || groups.recent.length > 0);

  return (
    <Disclose id="timers-suggestions" icon={faSeedling} iconClass="text-green" title="Suggestions">
      <div aria-live="polite">
        {luna.isPending ? (
          <>
            <p className="suggest-head suggest-head--luna">Luna Recommends</p>
            <p className="suggest">Considering your recent work…</p>
          </>
        ) : luna.isError ? (
          <>
            <p className="suggest-head suggest-head--luna">Luna Recommends</p>
            <p className="suggest">Luna is unavailable right now. Try again on your next visit.</p>
          </>
        ) : (
          <div className="suggest-group suggest-group--luna">
            <p className="suggest-head suggest-head--luna">
              <Icon icon={faLightbulb} className="text-orange" /> Luna Recommends
            </p>
            <div className="band-list">
              {luna.data.suggestions.length ? (
                luna.data.suggestions.map((s, index) => <SuggestionCard key={`${s.label}-${index}`} suggestion={s} />)
              ) : (
                <p className="suggest">{luna.data.advice_status}</p>
              )}
            </div>
          </div>
        )}
      </div>
      <form
        className="suggest luna-recommendation-controls"
        onSubmit={(event) => {
          event.preventDefault();
          refresh.mutate();
        }}
      >
        {bootstrap().profile.ai_features_enabled ? (
          <>
            <label className="sr-only" htmlFor="luna-effort">
              Reasoning effort
            </label>
            <select className="select" id="luna-effort" title="Reasoning effort" value={effort} onChange={(event) => setEffort(event.target.value)}>
              {EFFORTS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </>
        ) : null}
        <button type="submit" className="btn-icon" title="Refresh recommendations" disabled={refresh.isPending}>
          <Icon icon={faSyncAlt} spin={refresh.isPending} />
          <span className="sr-only">Refresh recommendations</span>
        </button>
        <a className="luna-usage-link" href="/timers/recommendation-usage/">
          Usage
        </a>
      </form>
      {hasHeuristics ? (
        <>
          <SuggestionGroup id="commitments" title="Commitment Push" icon={faBullseye} iconClass="text-yellow" items={groups!.commitments} />
          <SuggestionGroup id="habits" title="Usually Now" icon={faCalendarDay} iconClass="text-blue" items={groups!.habits} />
          <SuggestionGroup id="recent" title="Recent Presets" icon={faHistory} iconClass="text-green" items={groups!.recent} />
        </>
      ) : heuristics.isPending ? null : !luna.data?.suggestions.length ? (
        <p className="empty">No suggestions yet. They appear once you have a few sessions to learn from.</p>
      ) : null}
    </Disclose>
  );
}

function SuggestionGroup({
  id,
  title,
  icon,
  iconClass,
  items,
}: {
  id: string;
  title: string;
  icon: IconDefinition;
  iconClass: string;
  items: Suggestion[];
}) {
  if (!items.length) return null;
  return (
    <Disclose
      id={`suggest-${id}`}
      icon={icon}
      iconClass={iconClass}
      title={title}
      defaultOpen={false}
      slab={false}
      className="suggest-group"
      headClassName="suggest-disclose-head"
    >
      <div className="band-list">
        {items.map((s, index) => (
          <SuggestionCard key={`${s.label}-${index}`} suggestion={s} />
        ))}
      </div>
    </Disclose>
  );
}

function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const start = useStartTimer();
  const toast = useToast();
  const project = suggestion.project;
  return (
    <article className={`band suggest suggest--${suggestion.kind}`}>
      <div className="suggest-main">
        <span className="suggest-project">{suggestion.no_activity || !project ? suggestion.label : project.name}</span>
        {suggestion.kind === "luna" && suggestion.recommendation_score != null ? (
          <span className="suggest-score" title="Luna score" aria-label={`Luna score ${suggestion.recommendation_score.toFixed(2)}`}>
            {suggestion.recommendation_score.toFixed(2)}
          </span>
        ) : null}
        {suggestion.subprojects.length ? (
          <div className="suggest-subs">
            {suggestion.subprojects.map((sub) => (
              <span className="sub-chip" key={sub.id}>
                {sub.name}
              </span>
            ))}
          </div>
        ) : null}
        {suggestion.detail ? <span className="suggest-detail">{suggestion.detail}</span> : null}
        {suggestion.kind === "commitment" && suggestion.metric ? <span className="suggest-metric">{suggestion.metric}</span> : null}
      </div>
      {!suggestion.no_activity && project ? (
        <button
          type="button"
          className="suggest-start"
          title={`Start ${project.name}`}
          disabled={start.isPending}
          onClick={() =>
            start.mutate(
              {
                project_id: project.id,
                subproject_ids: suggestion.subprojects.map((s) => s.id),
                optimistic: { projectName: project.name, subprojects: suggestion.subprojects },
              },
              {
                onSuccess: () => toast.success(`Started ${project.name}.`),
                onError: (error) => toast.error(`Couldn't start the timer: ${errorMessage(error)}`),
              },
            )
          }
        >
          <Icon icon={faPlay} />
          <span className="sr-only">Start {project.name}</span>
        </button>
      ) : null}
    </article>
  );
}
