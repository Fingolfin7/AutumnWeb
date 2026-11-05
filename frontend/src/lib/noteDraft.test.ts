import { act, renderHook, waitFor } from "@testing-library/react";
import { ApiError } from "@/api/errors";
import { clearNoteDraft, readNoteDraft, useNoteDraft, writeNoteDraft } from "./noteDraft";

afterEach(() => {
  ["race", "offline", "conflict"].forEach((key) => clearNoteDraft(key));
  vi.restoreAllMocks();
});

it("serializes a newer edit behind an in-flight save and never clears its draft early", async () => {
  let finish!: (value: { version: number }) => void;
  const save = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; })).mockResolvedValue({ version: 3 });
  const { result } = renderHook(() => useNoteDraft({ draftKey: "race", text: "original", version: 1, save }));
  act(() => result.current.change("first"));
  let saving!: Promise<boolean>;
  act(() => { saving = result.current.flush(); });
  act(() => result.current.change("second"));
  expect(readNoteDraft("race")?.text).toBe("second");
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => { finish({ version: 2 }); await saving; });
  expect(save.mock.calls).toEqual([["first", 1], ["second", 2]]);
  expect(result.current.value).toBe("second");
  expect(result.current.status).toBe("Saved");
  expect(readNoteDraft("race")).toBeNull();
});

it("recovers an offline draft after remount and adopts the confirmed timer version", async () => {
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  const save = vi.fn().mockResolvedValue({ version: 2 });
  const first = renderHook(() => useNoteDraft({ draftKey: "offline", text: "", version: 0, save, enabled: false }));
  act(() => first.result.current.change("written before sync"));
  first.unmount();
  online.mockReturnValue(true);
  const second = renderHook(() => useNoteDraft({ draftKey: "offline", text: "", version: 1, save, enabled: true, revision: 42 }));
  expect(second.result.current.value).toBe("written before sync");
  await waitFor(() => expect(save).toHaveBeenCalledWith("written before sync", 1));
  await waitFor(() => expect(second.result.current.status).toBe("Saved"));
});

it("keeps a conflicted note and its original version through reload and reconnect", async () => {
  writeNoteDraft("conflict", { text: "my offline reflection", version: 4 });
  const save = vi.fn().mockRejectedValue(new ApiError(409, "version_conflict", "Changed elsewhere"));
  const { result } = renderHook(() => useNoteDraft({ draftKey: "conflict", text: "CLI reflection", version: 5, save }));
  await waitFor(() => expect(result.current.status).toContain("changed elsewhere"));
  expect(save).toHaveBeenCalledWith("my offline reflection", 4);
  expect(result.current.value).toBe("my offline reflection");
  expect(readNoteDraft("conflict")).toEqual({ text: "my offline reflection", version: 4 });
  act(() => window.dispatchEvent(new Event("online")));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save).toHaveBeenLastCalledWith("my offline reflection", 4);
});
