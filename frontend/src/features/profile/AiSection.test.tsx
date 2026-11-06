import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AiSection } from "./AiSection";
import type { Prefs } from "./model";

const actions = vi.hoisted(() => ({ put: vi.fn(), remove: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("@/app/toasts", () => ({ useToast: () => actions }));
vi.mock("./api", () => ({
  putApiKey: actions.put, deleteApiKey: actions.remove,
  disconnectChatGPT: vi.fn(), startChatGPTLogin: vi.fn(),
  meKeys: { chatgpt: () => ["chatgpt"] },
  useChatGPTLogin: () => ({ data: { status: "disconnected" }, isPending: false, refetch: vi.fn() }),
  useOnCodexConnected: vi.fn(),
}));

it("saves and removes only the selected provider key", async () => {
  actions.put.mockResolvedValue({}); actions.remove.mockResolvedValue({});
  const prefs = { configured_api_keys: { gemini: false, openai: true, openai_chatgpt: false, claude: false }, openai_source: "profile" } as unknown as Prefs;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AiSection prefs={prefs} luna="low" onLuna={vi.fn()} errors={{}} /></QueryClientProvider>);
  fireEvent.click(screen.getByText("Gemini"));
  const gemini = screen.getByText("Gemini").closest("details")!;
  fireEvent.change(within(gemini).getByLabelText("API key"), { target: { value: "fictional-key" } });
  fireEvent.click(within(gemini).getByRole("button", { name: "Save key" }));
  await waitFor(() => expect(actions.put).toHaveBeenCalledWith("gemini", "fictional-key"));
  await waitFor(() => expect(within(gemini).getByLabelText("API key")).toHaveValue(""));
  fireEvent.click(screen.getByText("OpenAI API key"));
  const openai = screen.getByText("OpenAI API key").closest("details")!;
  fireEvent.click(within(openai).getByRole("button", { name: "Remove key" }));
  await waitFor(() => expect(actions.remove).toHaveBeenCalledWith("openai"));
});

it("keeps an unsaved key available when the provider action fails", async () => {
  actions.put.mockRejectedValueOnce(new Error("Connection failed"));
  const prefs = { configured_api_keys: { gemini: false, openai: false, openai_chatgpt: false, claude: false }, openai_source: null } as unknown as Prefs;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><AiSection prefs={prefs} luna="low" onLuna={vi.fn()} errors={{}} /></QueryClientProvider>);
  fireEvent.click(screen.getByText("Claude"));
  const row = screen.getByText("Claude").closest("details")!;
  fireEvent.change(within(row).getByLabelText("API key"), { target: { value: "fictional-key" } });
  fireEvent.click(within(row).getByRole("button", { name: "Save key" }));
  expect(await within(row).findByRole("alert")).toBeVisible();
  expect(within(row).getByLabelText("API key")).toHaveValue("fictional-key");
});
