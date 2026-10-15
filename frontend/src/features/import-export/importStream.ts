/* The import progress stream (core/api_v2/import_export.py, ImportUploadStreamView):
   Server-sent events whose data is {"message": "..."}, one line per step of
   core.importer.iter_import. Same rules the old page's JS applied. */

export type LogKind = "error" | "success" | "warning" | "info";

export function classifyMessage(message: string): LogKind {
  const lower = message.toLowerCase();
  if (lower.includes("error")) return "error";
  if (lower.includes("success")) return "success";
  if (lower.includes("warning")) return "warning";
  return "info";
}

/* "Processing project 3/12: Name" -> 25 percent (the amount done before this
   project starts is not counted: the bar shows the project being worked on). */
export function projectProgress(message: string): { current: number; total: number; percent: number } | null {
  const match = /Processing project (\d+)\/(\d+)/.exec(message);
  if (!match) return null;
  const current = Number(match[1]);
  const total = Number(match[2]);
  if (!total) return null;
  return { current, total, percent: Math.min(100, (current / total) * 100) };
}

/* The stream ends after a completion line or an error line. */
export function isFinal(message: string): boolean {
  return message.includes("completed") || message.toLowerCase().includes("error");
}

export function succeeded(message: string): boolean {
  return message.includes("completed successfully");
}

/* A data payload is JSON; anything else is shown as it came. */
export function parseEvent(data: string): string {
  try {
    const parsed = JSON.parse(data) as { message?: unknown };
    return typeof parsed.message === "string" ? parsed.message : String(data);
  } catch {
    return data;
  }
}

/* The stream is read with fetch, not EventSource: EventSource always asks for
   Accept: text/event-stream, which the API's content negotiation rejects (a
   500 from ImportUploadStreamView; see report). fetch can ask for anything,
   so the server-sent events are parsed by hand. */
export function parseSseBuffer(buffer: string): { messages: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: string[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (data) messages.push(parseEvent(data));
  }
  return { messages, rest };
}
