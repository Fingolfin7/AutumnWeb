import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { focusManager, QueryClient, QueryObserver } from "@tanstack/react-query";
import { watchAttention } from "./attention";

const IDLE = 60_000;

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("watchAttention", () => {
  let stop: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
    stop = watchAttention(IDLE);
  });

  afterEach(() => {
    stop();
    focusManager.setFocused(undefined);
    vi.useRealTimers();
  });

  it("goes unfocused after the idle time and refocuses on input", () => {
    expect(focusManager.isFocused()).toBe(true);
    vi.advanceTimersByTime(IDLE + 1);
    expect(focusManager.isFocused()).toBe(false);
    window.dispatchEvent(new Event("pointerdown"));
    expect(focusManager.isFocused()).toBe(true);
  });

  it("keeps focus while input continues", () => {
    for (let i = 0; i < 5; i++) {
      vi.advanceTimersByTime(IDLE / 2);
      window.dispatchEvent(new Event("keydown"));
    }
    expect(focusManager.isFocused()).toBe(true);
  });

  it("follows tab visibility", () => {
    setVisibility("hidden");
    expect(focusManager.isFocused()).toBe(false);
    setVisibility("visible");
    expect(focusManager.isFocused()).toBe(true);
  });

  it("pauses refetchInterval while idle and refetches stale data on return", async () => {
    const client = new QueryClient();
    client.mount(); // as QueryClientProvider does: subscribes to focusManager
    const queryFn = vi.fn(async () => 1);
    const observer = new QueryObserver(client, {
      queryKey: ["poll"],
      queryFn,
      refetchInterval: 15_000,
      staleTime: 5_000,
    });
    const unsubscribe = observer.subscribe(() => {});
    await vi.advanceTimersByTimeAsync(0);
    expect(queryFn).toHaveBeenCalledTimes(1);

    // Polls at 15, 30 and 45 s; at 60 s the idle timer (armed first) wins.
    await vi.advanceTimersByTimeAsync(IDLE);
    const beforeIdle = queryFn.mock.calls.length;
    expect(beforeIdle).toBe(4);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(queryFn).toHaveBeenCalledTimes(beforeIdle);

    window.dispatchEvent(new Event("pointermove"));
    await vi.advanceTimersByTimeAsync(0);
    expect(queryFn).toHaveBeenCalledTimes(beforeIdle + 1);
    unsubscribe();
    client.unmount();
    client.clear();
  });
});
