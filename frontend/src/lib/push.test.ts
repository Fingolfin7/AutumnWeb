import { api } from "@/api/client";
import { decodeBase64Url, describePushError, pushStatus, sameApplicationServerKey, sendTestPush } from "./push";

vi.mock("@/api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() },
  unwrap: async (promise: Promise<{ data?: unknown }>) => (await promise).data,
}));

const key = new Uint8Array(65);
key[0] = 4;
for (let i = 1; i < 65; i += 1) key[i] = i;
const encoded = btoa(String.fromCharCode(...key)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

it("decodes a P-256 VAPID public key", () => {
  expect(Array.from(decodeBase64Url(encoded))).toEqual(Array.from(key));
});

it("rejects malformed keys", () => {
  expect(() => decodeBase64Url("not a key!")).toThrow(/invalid/);
  expect(() => decodeBase64Url("AAAA")).toThrow(/invalid/);
});

it("compares application server keys byte for byte", () => {
  expect(sameApplicationServerKey(key.buffer, key)).toBe(true);
  const other = key.slice();
  other[5] = 99;
  expect(sameApplicationServerKey(other.buffer, key)).toBe(false);
  expect(sameApplicationServerKey(null, key)).toBe(true);
});

it("names browser push errors", () => {
  const error = new Error("Registration failed - push service error");
  error.name = "AbortError";
  expect(describePushError(error, "x")).toBe("AbortError: Registration failed - push service error");
  expect(describePushError(new Error("Plain"), "x")).toBe("Plain");
});

it("reads push status from the v2 API", async () => {
  vi.mocked(api.GET).mockResolvedValueOnce({ data: { available: true, subscribed: true }, response: new Response() } as never);
  expect((await pushStatus()).subscribed).toBe(true);
  expect(api.GET).toHaveBeenCalledWith("/api/v2/push/status/");
});

it("queues a test notification with a bodyless POST to the v2 API", async () => {
  vi.mocked(api.POST).mockResolvedValueOnce({ data: { queued: true, event_id: 3 }, response: new Response() } as never);
  expect((await sendTestPush()).queued).toBe(true);
  expect(api.POST).toHaveBeenCalledWith("/api/v2/push/test/");
});
