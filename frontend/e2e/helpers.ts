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

/** Resolves once the service worker controls the page and has saved every
    file of the build. Going offline earlier leaves pages that cannot load: a
    page's own file may be saved while a shared file it imports is not.
    (expect.poll over page.evaluate, which waits for the async check;
    waitForFunction takes the pending promise itself as a truthy answer.) */
export async function buildSavedOffline(page: Page) {
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          if (!navigator.serviceWorker.controller) return false;
          const manifest = (await (await fetch("/static/app/manifest.json")).json()) as Record<string, { file?: string; css?: string[]; assets?: string[] }>;
          const wanted = Object.values(manifest)
            .flatMap((chunk) => [chunk.file, ...(chunk.css ?? []), ...(chunk.assets ?? [])])
            .filter((file): file is string => !!file)
            .map((file) => new URL(`/static/app/${file}`, location.origin).href);
          const names = await caches.keys();
          const saved = new Set((await Promise.all(names.map(async (name) => (await (await caches.open(name)).keys()).map((r) => r.url)))).flat());
          return wanted.length > 0 && wanted.every((url) => saved.has(url));
        }),
      { timeout: 30_000, intervals: [500] },
    )
    .toBe(true);
}
