import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { CHART_STALE, fetchChart, parseRelatedHeader, semanticSearchAvailable, useChartData } from "./api";
import { buildChartQuery, EMPTY_FILTERS, type ChartQuery } from "./filters";

/* Ported from scripts/tests/charts_related.test.cjs: the "Including related"
   pill must follow the chart on screen. Its state is the X-Autumn-Related of
   the response, kept with the cached payload, and a response that arrives for
   an older render must never overwrite the current one. */
const GET = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api: { GET }, unwrap: vi.fn() }));

interface Pending {
  query: ChartQuery;
  reply: (state: string | null) => void;
}
let pending: Pending[] = [];

beforeEach(() => {
  pending = [];
  GET.mockReset();
  GET.mockImplementation(
    (_url: string, init: { params: { query: ChartQuery } }) =>
      new Promise((resolve) => {
        pending.push({
          query: init.params.query,
          reply: (state) =>
            resolve({
              data: [{ count: 1 }],
              response: { ok: true, status: 200, headers: new Headers(state ? { "X-Autumn-Related": state } : {}) },
            }),
        });
      }),
  );
});

const related = (type: ChartQuery["chart_type"]) => buildChartQuery({ ...EMPTY_FILTERS, chart_type: type, search: "oauth", related: true }, {}, null);

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

it("related requests carry related=true", async () => {
  const request = fetchChart(related("pie"));
  expect(pending[0]!.query.related).toBe(true);
  pending[0]!.reply("included");
  await request;
});

it("reads the header, ignoring anything unexpected", () => {
  expect(parseRelatedHeader("included")).toBe("included");
  expect(parseRelatedHeader("unavailable")).toBe("unavailable");
  expect(parseRelatedHeader(null)).toBeNull();
  expect(parseRelatedHeader("whatever")).toBeNull();
});

it("a cached chart shows its own related state", async () => {
  const { wrapper } = setup();
  const hook = renderHook(({ query }) => useChartData(query, true), { wrapper, initialProps: { query: related("pie") } });
  await waitFor(() => expect(pending).toHaveLength(1));
  pending[0]!.reply("included");
  await waitFor(() => expect(hook.result.current.data?.related).toBe("included"));

  hook.rerender({ query: related("bar") });
  await waitFor(() => expect(pending).toHaveLength(2));
  pending[1]!.reply("unavailable");
  await waitFor(() => expect(hook.result.current.data?.related).toBe("unavailable"));

  hook.rerender({ query: related("pie") });
  await waitFor(() => expect(hook.result.current.data?.related).toBe("included"));
  expect(pending).toHaveLength(2); // served from the cache
  expect(CHART_STALE).toBeGreaterThan(0);
});

it("a late response for an older chart does not change the pill", async () => {
  const { wrapper } = setup();
  const hook = renderHook(({ query }) => useChartData(query, true), { wrapper, initialProps: { query: related("pie") } });
  await waitFor(() => expect(pending).toHaveLength(1));
  hook.rerender({ query: related("bar") });
  await waitFor(() => expect(pending).toHaveLength(2));
  pending[1]!.reply("included");
  await waitFor(() => expect(hook.result.current.data?.related).toBe("included"));
  await act(async () => pending[0]!.reply("unavailable"));
  expect(hook.result.current.data?.related).toBe("included");
});

it("a response that outlived a Refresh does not overwrite the newer state", async () => {
  const { client, wrapper } = setup();
  const hook = renderHook(() => useChartData(related("pie"), true), { wrapper });
  await waitFor(() => expect(pending).toHaveLength(1));
  await act(async () => pending[0]!.reply("included"));
  await waitFor(() => expect(hook.result.current.data?.related).toBe("included"));

  const refresh = async () => {
    await act(async () => {
      void client.invalidateQueries({ queryKey: ["reports", "charts"] });
    });
  };
  await refresh(); // request 2 goes out...
  await waitFor(() => expect(pending).toHaveLength(2));
  await refresh(); // ...and is superseded by request 3 before it answers
  await waitFor(() => expect(pending).toHaveLength(3));
  await act(async () => pending[2]!.reply("included"));
  await act(async () => pending[1]!.reply("unavailable"));
  expect(hook.result.current.data?.related).toBe("included");
});

it("related search needs AI features and a stored OpenAI key", () => {
  const profile = { ai_features_enabled: true, openai_key_configured: true };
  expect(semanticSearchAvailable(profile)).toBe(true);
  expect(semanticSearchAvailable({ ...profile, openai_key_configured: false })).toBe(false);
  expect(semanticSearchAvailable({ ...profile, ai_features_enabled: false })).toBe(false);
});
