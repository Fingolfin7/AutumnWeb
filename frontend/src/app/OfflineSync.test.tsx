import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { OfflineSync } from "./OfflineSync";
import { enqueueStart, flushQueue, resetQueueForTests } from "@/lib/offlineQueue";

const mocks = vi.hoisted(() => ({ invalidate: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/api/sync", () => ({ useInvalidate: () => mocks.invalidate }));
vi.mock("./toasts", () => ({ useToast: () => mocks.toast }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetQueueForTests();
});

it("warns about memory-only changes and clears the warning after successful sync", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage full"); });
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  enqueueStart({ uuid: "memory", body: { project_id: 3, start: "2026-10-14T07:00:00Z", uuid: "memory" }, display: { projectName: "Gym", subprojects: [] } });
  render(<OfflineSync />);
  expect(screen.getByRole("status")).toHaveTextContent("only saved in this tab");
  expect(screen.getByRole("status")).toHaveTextContent("reloading or closing it may lose them");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"id":42}', { status: 201 })));
  await act(async () => { await flushQueue(); });
  expect(screen.getByRole("status")).not.toHaveTextContent("only saved in this tab");
});
