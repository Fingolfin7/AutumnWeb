import { QueryClient } from "@tanstack/react-query";
import { currentRun, dismissRun, startRun, stopStream } from "./runStore";
import { insightKeys } from "./keys";
import type { StreamRequest } from "./types";

/* No provider is ever contacted: fetch is replaced by a canned SSE body. */
const body: StreamRequest = { message: "How was my week?", provider: "openai", model: "gpt-a" };
const CHAT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function sseResponse(chunks: string[], init: ResponseInit = { status: 200 }, hold?: Promise<void>) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
        await Promise.resolve();
      }
      if (hold) await hold;
      controller.close();
    },
  });
  return new Response(stream, { ...init, headers: { "Content-Type": "text/event-stream" } });
}

const events = [
  `event: chat\ndata: ${JSON.stringify({ chat_id: CHAT, chat_url: `/insights/${CHAT}/`, stream_url: "x" })}\n\n`,
  'event: delta\ndata: {"content":"You "}\n\n',
  ": keep-alive\n\n",
  'event: delta\ndata: {"content":"wrote."}\n\n',
  `event: done\ndata: ${JSON.stringify({ chat_id: CHAT, content: "You wrote.", html: "<p>You wrote.</p>", sources: [], usage: { prompt: 3, response: 2 }, model: "gpt-a" })}\n\n`,
];

function setup() {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const args = { client, body, baseCount: 0, chatModel: "openai:gpt-a", seedFilters: { start_date: "2026-09-14" } };
  return { client, invalidate, args };
}

afterEach(() => {
  vi.unstubAllGlobals();
  const run = currentRun();
  if (run) dismissRun(run.id);
});

it("streams an answer, seeds the new chat for the page that takes over, and lets go once saved", async () => {
  const fetchMock = vi.fn(async () => sseResponse(events));
  vi.stubGlobal("fetch", fetchMock);
  const { client, invalidate, args } = setup();

  await startRun(args);

  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/v2/insights/stream/");
  expect(init.method).toBe("POST");
  expect(JSON.parse(String(init.body))).toEqual(body);
  expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  expect(init.headers).toHaveProperty("X-CSRFToken");

  const seeded = client.getQueryData<{ id: string; model: string; messages: unknown[] }>(insightKeys.chat(CHAT));
  expect(seeded).toMatchObject({ id: CHAT, model: "openai:gpt-a", messages: [] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: insightKeys.chats() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: insightKeys.chat(CHAT) });
  /* A saved answer is dropped from the store. */
  expect(currentRun()).toBeNull();
});

it("keeps a failed exchange on screen and reports the server's refusal", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => sseResponse(['event: error\ndata: {"message": "Insights requires an AI provider API key."}\n\n'], { status: 403 })),
  );
  await startRun(setup().args);
  expect(currentRun()).toMatchObject({ status: "error", text: "Error: Insights requires an AI provider API key." });
});

it("reads the API's JSON errors too", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ error: { code: "not_found", message: "Chat not found.", details: null } }), { status: 404 })),
  );
  await startRun(setup().args);
  expect(currentRun()).toMatchObject({ status: "error", text: "Error: Chat not found." });
});

it("a network failure is an error run, not an exception", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
  await startRun(setup().args);
  expect(currentRun()?.status).toBe("error");
  expect(currentRun()?.text).toContain("Can't reach Autumn");
});

it("Stop ends the read, keeps the partial answer and marks it stopped", async () => {
  let release!: () => void;
  const hold = new Promise<void>((resolve) => (release = resolve));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      const response = sseResponse(events.slice(0, 2), { status: 200 }, hold);
      init.signal?.addEventListener("abort", () => release());
      return response;
    }),
  );
  const running = startRun(setup().args);
  await vi.waitFor(() => expect(currentRun()?.text).toBe("You "));
  stopStream();
  await running;
  expect(currentRun()).toMatchObject({ status: "stopped", text: "You " });
});

it("a stream that ends without done is reported rather than left spinning", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => sseResponse([events[0]!])));
  await startRun(setup().args);
  expect(currentRun()).toMatchObject({ status: "error", chatId: CHAT });
});
