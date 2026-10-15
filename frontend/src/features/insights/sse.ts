/* A small Server-Sent Events parser for a fetch() response body. openapi-fetch
   cannot hand over a streamed body, so the Insights stream reads response.body
   itself and feeds the decoded text through this.

   Follows the SSE wire format: lines end in LF, CRLF or a lone CR (a CR at the
   end of a chunk may be the first half of a CRLF); a blank line dispatches the
   event; "event:" names it; one or more "data:" lines are joined with "\n";
   lines starting with ":" are comments (the server's keep-alives); a single
   space after the colon is dropped. Chunks may split anywhere, even mid-line. */
export interface SseEvent {
  /** "message" unless an event: line named it. */
  event: string;
  data: string;
}

export interface SseParser {
  /** Feed decoded text; returns the events it completed. */
  push(chunk: string): SseEvent[];
  /** The stream ended: dispatch an event the server never closed with a blank line. */
  flush(): SseEvent[];
}

export function createSseParser(): SseParser {
  let carry = ""; // an unfinished line
  let skipLf = false; // the previous chunk ended in CR
  let event = "message";
  let data: string[] = [];
  let hasData = false;

  const out: SseEvent[] = [];

  const dispatch = () => {
    if (hasData) out.push({ event, data: data.join("\n") });
    event = "message";
    data = [];
    hasData = false;
  };

  const line = (text: string) => {
    if (text === "") return dispatch();
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value || "message";
    else if (field === "data") {
      data.push(value);
      hasData = true;
    }
  };

  return {
    push(chunk) {
      out.length = 0;
      let text = carry + chunk;
      carry = "";
      if (skipLf) {
        if (text.startsWith("\n")) text = text.slice(1);
        skipLf = false;
      }
      let start = 0;
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch !== "\n" && ch !== "\r") continue;
        line(text.slice(start, i));
        if (ch === "\r") {
          if (text[i + 1] === "\n") i++;
          else if (i + 1 === text.length) skipLf = true;
        }
        start = i + 1;
      }
      carry = text.slice(start);
      return out.slice();
    },
    flush() {
      out.length = 0;
      if (carry) line(carry);
      carry = "";
      dispatch();
      return out.slice();
    },
  };
}

/* The Insights stream's payloads are JSON; anything else is shown as a message
   (what insights_stream.js did). */
export function parsePayload(data: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(data);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch {
    /* not JSON */
  }
  return { message: data };
}

/** Read a response body to its end, calling onEvent for each SSE event. */
export async function readSse(body: ReadableStream<Uint8Array>, onEvent: (event: SseEvent) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      const text = done ? decoder.decode() : decoder.decode(value, { stream: true });
      for (const event of parser.push(text)) onEvent(event);
      if (done) break;
    }
    for (const event of parser.flush()) onEvent(event);
  } finally {
    reader.releaseLock();
  }
}
