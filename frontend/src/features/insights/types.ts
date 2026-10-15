import type { components } from "@/api/schema";

type S = components["schemas"];

export type ChatGroup = S["InsightChatGroup"];
export type ChatSummary = S["InsightChatSummary"];
export type ChatDetail = S["InsightChatDetail"];
export type ChatMessage = S["InsightMessage"];
export type ChatFiltersStored = S["InsightFilters"];
export type InsightOptions = S["InsightOptions"];
export type ProviderOption = S["InsightProviderOption"];
export type ModelOption = S["InsightModelOption"];
export type Source = S["InsightSource"];
export type Usage = S["InsightUsage"];
export type StreamRequest = S["InsightStreamRequest"];
