import { QueryClient, dehydrate } from "@tanstack/react-query";
import { expect, it } from "vitest";
import { ApiError } from "@/api/errors";
import { isUnreachable, savedDataCache } from "./savedData";

const client = () => new QueryClient({ queryCache: savedDataCache(), defaultOptions: { queries: { retry: false } } });
const unreachable = () => Promise.reject(new ApiError(0, "network", "Can't reach Autumn."));

it("keeps a query's data, and its saved copy, when a refresh can't reach Autumn", async () => {
  const c = client();
  await c.fetchQuery({ queryKey: ["timers"], queryFn: () => ["running"] });
  await c.fetchQuery({ queryKey: ["timers"], queryFn: unreachable }).catch(() => undefined);

  expect(c.getQueryState(["timers"])).toMatchObject({ status: "success", data: ["running"], error: null });
  /* What persist.ts would write to the device. */
  expect(dehydrate(c).queries.map((q) => q.queryKey)).toEqual([["timers"]]);
  expect(isUnreachable()).toBe(true);

  await c.fetchQuery({ queryKey: ["timers"], queryFn: () => [] });
  expect(isUnreachable()).toBe(false);
});

it("still reports the failure when there is nothing saved, or the server refused", async () => {
  const c = client();
  await c.fetchQuery({ queryKey: ["projects"], queryFn: unreachable }).catch(() => undefined);
  expect(c.getQueryState(["projects"])?.status).toBe("error");

  await c.fetchQuery({ queryKey: ["sessions"], queryFn: () => ["a"] });
  await c
    .fetchQuery({ queryKey: ["sessions"], queryFn: () => Promise.reject(new ApiError(403, "forbidden", "No.")) })
    .catch(() => undefined);
  expect(c.getQueryState(["sessions"])?.status).toBe("error");
});
