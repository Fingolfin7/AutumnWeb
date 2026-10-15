import { expect, type Locator, type Page } from "@playwright/test";

/** Collects uncaught page errors and console errors until read. */
export function trackErrors(page: Page): () => string[] {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") problems.push(`console: ${msg.text()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) problems.push(`HTTP ${response.status()} ${response.url()}`);
  });
  return () => problems;
}

/** The toast region; toasts are role=status/alert children of it. */
export const toasts = (page: Page): Locator => page.getByRole("region", { name: "Notifications" });

/** Pick a project in the "Project" combobox (start timer, edit session). */
export async function pickProject(page: Page, name: string): Promise<void> {
  const combobox = page.getByRole("combobox", { name: "Project" });
  await combobox.fill(name);
  await page.getByRole("option", { name }).click();
  await expect(combobox).toHaveValue(name);
}

/** Stops nothing, saves nothing: removes every running timer through the API. */
export async function discardTimers(page: Page): Promise<void> {
  if (page.url() === "about:blank") await page.goto("/");
  const csrf = (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value ?? "";
  const response = await page.request.get("/api/v2/timers/");
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { timers: { id: number }[] };
  for (const timer of body.timers) {
    const removed = await page.request.delete(`/api/v2/timers/${timer.id}`, { headers: { "X-CSRFToken": csrf } });
    expect(removed.ok(), `discard timer ${timer.id}`).toBeTruthy();
  }
}
