/* Query keys for Insights. "insights" is deliberately not in the set the app
   keeps on the device (app/persist.ts): chat transcripts stay off local
   storage. */
export const insightKeys = {
  all: () => ["insights"] as const,
  options: () => ["insights", "options"] as const,
  chats: () => ["insights", "chats"] as const,
  chat: (id: string) => ["insights", "chat", id] as const,
  preview: (params: object) => ["insights", "preview", params] as const,
};
