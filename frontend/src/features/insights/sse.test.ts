import { createSseParser, parsePayload, readSse, type SseEvent } from "./sse";

function parseAll(chunks: string[]): SseEvent[] {
  const parser = createSseParser();
  const events: SseEvent[] = [];
  for (const chunk of chunks) events.push(...parser.push(chunk));
  events.push(...parser.flush());
  return events;
}

describe("createSseParser", () => {
  it("parses named events in the server's format", () => {
    const wire = 'event: chat\ndata: {"chat_id":"a"}\n\nevent: delta\ndata: {"content":"Hi"}\n\n';
    expect(parseAll([wire])).toEqual([
      { event: "chat", data: '{"chat_id":"a"}' },
      { event: "delta", data: '{"content":"Hi"}' },
    ]);
  });

  it("is the same however the stream is chunked, even one character at a time", () => {
    const wire = 'event: delta\ndata: {"content":"a b"}\n\n: keep-alive\n\nevent: done\ndata: {"content":"ab"}\n\n';
    const whole = parseAll([wire]);
    expect(parseAll([...wire])).toEqual(whole);
    expect(parseAll([wire.slice(0, 13), wire.slice(13, 40), wire.slice(40)])).toEqual(whole);
    expect(whole).toHaveLength(2);
  });

  it("joins multi-line data with a newline", () => {
    expect(parseAll(["data: one\ndata: two\ndata:three\n\n"])).toEqual([{ event: "message", data: "one\ntwo\nthree" }]);
  });

  it("ignores comments, keep-alives and events without data", () => {
    expect(parseAll([": keep-alive\n\nevent: ping\n\nid: 4\ndata: x\n\n"])).toEqual([{ event: "message", data: "x" }]);
  });

  it("accepts CRLF and lone CR line endings, including a CRLF split across chunks", () => {
    const expected = [{ event: "delta", data: "x" }];
    expect(parseAll(["event: delta\r\ndata: x\r\n\r\n"])).toEqual(expected);
    expect(parseAll(["event: delta\rdata: x\r\r"])).toEqual(expected);
    expect(parseAll(["event: delta\r", "\ndata: x\r", "\n\r", "\n"])).toEqual(expected);
  });

  it("drops one leading space only, and keeps colons inside the value", () => {
    expect(parseAll(["data:  two spaces: here\n\n"])).toEqual([{ event: "message", data: " two spaces: here" }]);
  });

  it("flush dispatches an event the stream ended in the middle of", () => {
    expect(parseAll(["event: done\ndata: {}"])).toEqual([{ event: "done", data: "{}" }]);
    expect(parseAll(["event: done\ndata: {}\n"])).toEqual([{ event: "done", data: "{}" }]);
  });

  it("does not leak the event name into the next event", () => {
    expect(parseAll(["event: error\ndata: a\n\ndata: b\n\n"])).toEqual([
      { event: "error", data: "a" },
      { event: "message", data: "b" },
    ]);
  });
});

describe("parsePayload", () => {
  it("parses JSON objects and wraps anything else as a message", () => {
    expect(parsePayload('{"content":"x"}')).toEqual({ content: "x" });
    expect(parsePayload("Server blew up")).toEqual({ message: "Server blew up" });
    expect(parsePayload("[1,2]")).toEqual({ message: "[1,2]" });
  });
});

describe("readSse", () => {
  it("decodes a byte stream whose chunks split a multibyte character", async () => {
    const bytes = new TextEncoder().encode('event: delta\ndata: {"content":"café"}\n\n');
    const cut = bytes.indexOf(0xc3) + 1; // between the two bytes of "e acute"
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut));
        controller.enqueue(bytes.slice(cut));
        controller.close();
      },
    });
    const seen: SseEvent[] = [];
    await readSse(body, (event) => seen.push(event));
    expect(seen).toEqual([{ event: "delta", data: '{"content":"café"}' }]);
  });
});
