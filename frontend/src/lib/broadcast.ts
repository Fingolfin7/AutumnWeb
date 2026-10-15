/* Cross-tab nudges. A mutation in one tab (start a timer, edit a session)
   tells the other open tabs which data went stale, so a second window or the
   installed PWA catches up at once instead of on its next poll. */
export type BroadcastTopic = "timers" | "sessions" | "projects" | "commitments" | "meta";

const CHANNEL = "autumn-sync";
let channel: BroadcastChannel | null = null;

function getChannel(): BroadcastChannel | null {
  if (channel || typeof BroadcastChannel === "undefined") return channel;
  channel = new BroadcastChannel(CHANNEL);
  return channel;
}

export function announce(...topics: BroadcastTopic[]) {
  getChannel()?.postMessage({ topics });
}

export function listen(handler: (topics: BroadcastTopic[]) => void): () => void {
  const ch = getChannel();
  if (!ch) return () => {};
  const onMessage = (event: MessageEvent) => {
    const topics = (event.data as { topics?: BroadcastTopic[] })?.topics;
    if (Array.isArray(topics)) handler(topics);
  };
  ch.addEventListener("message", onMessage);
  return () => ch.removeEventListener("message", onMessage);
}
