import { expect, test } from "@playwright/test";
import { discardTimers, pickProject, toasts, trackErrors } from "./helpers";

test.beforeEach(async ({ page }) => {
  await discardTimers(page);
});
test.afterEach(async ({ page }) => {
  await discardTimers(page);
});

test("timer lifecycle: start, see it running, stop with a note, find the session", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  // Unique per attempt, or the session search finds earlier attempts too.
  const note = `Lifecycle check ${testInfo.project.name} ${testInfo.retry}.${testInfo.repeatEachIndex}`;

  await page.goto("/start_timer/");
  await pickProject(page, "Garden Planner App");
  await page.getByRole("button", { name: "Start timer" }).click();

  await expect(page).toHaveURL(/\/timers\/$/);
  const card = page.getByRole("article", { name: "Running timer: Garden Planner App" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Running", { exact: true })).toBeVisible();

  await page.goto("/");
  await expect(page.getByRole("article", { name: "Running timer: Garden Planner App" })).toBeVisible();

  await page.goto("/timers/");
  await page.getByRole("article", { name: "Running timer: Garden Planner App" }).getByRole("link", { name: "Stop" }).click();
  await expect(page).toHaveURL(/\/stop_timer\/\d+\/$/);
  await page.getByRole("textbox", { name: "Note", exact: true }).fill(note);
  await page.getByRole("button", { name: "Stop timer" }).click();

  await expect(page).toHaveURL(/\/timers\/$/);
  await expect(page.getByRole("article", { name: /Running timer/ })).toHaveCount(0);
  await expect(toasts(page).getByRole("status").first()).toBeVisible();

  await page.goto(`/sessions/?search=${encodeURIComponent(note)}`);
  const list = page.getByRole("region", { name: "Sessions" });
  await expect(list.getByText(note)).toBeVisible();
  await expect(list.getByRole("link", { name: "Garden Planner App" })).toBeVisible();
  expect(problems()).toEqual([]);
});

test.describe("offline", () => {
  test.use({ serviceWorkers: "allow" });

  test("a timer started offline is saved, then synced when the connection returns", async ({ page, context }) => {
    // Load the app online so the service worker, the build and the project list are cached.
    await page.goto("/timers/");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload();
    await page.waitForFunction(async () => {
      if (!navigator.serviceWorker.controller) return false;
      const names = (await caches.keys()).filter((name) => name.startsWith("autumn-pwa-app"));
      if (!names.length) return false;
      const cache = await caches.open(names[0]!);
      return (await cache.keys()).length > 5;
    });
    await page.goto("/start_timer/");
    await expect(page.getByRole("combobox", { name: "Project" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2_500); // the query cache is persisted on a throttle

    await context.setOffline(true);
    await expect(page.getByText(/Offline/)).toBeVisible();
    await pickProject(page, "Piano Practice");
    await page.getByRole("button", { name: "Start timer" }).click();

    const card = page.getByRole("article", { name: "Running timer: Piano Practice" });
    await expect(card).toBeVisible();
    await expect(card.getByText("Running · saved offline")).toBeVisible();

    await context.setOffline(false);
    await expect(toasts(page).getByText(/Synced 1 offline change/)).toBeVisible({ timeout: 30_000 });
    await expect(card.getByText("Running · saved offline")).toHaveCount(0);
    await expect(card.getByText("Running", { exact: true })).toBeVisible();
  });
});

test("a timer started outside the active context is announced, and Show all reveals it", async ({ page }) => {
  const problems = trackErrors(page);
  const contextSwitch = page.getByRole("combobox", { name: "Active context" });
  try {
    await page.goto("/timers/");
    // The switch is saved by a PATCH; let it land before leaving the page.
    const saved = page.waitForResponse((r) => r.url().includes("/api/v2/me/preferences/") && r.request().method() === "PATCH");
    await contextSwitch.selectOption({ label: "Study" });
    expect((await saved).ok()).toBeTruthy();

    await page.goto("/start_timer/");
    await pickProject(page, "Garden Planner App"); // a Work project
    await page.getByRole("button", { name: "Start timer" }).click();

    await expect(page).toHaveURL(/\/timers\/$/);
    const notice = page.getByText("1 timer running in other contexts");
    await expect(notice).toBeVisible();
    await expect(page.getByRole("article", { name: /Running timer/ })).toHaveCount(0);

    await page.getByRole("button", { name: "Show all" }).click();
    await expect(contextSwitch).toHaveValue("all");
    await expect(page.getByRole("article", { name: "Running timer: Garden Planner App" })).toBeVisible();
    await expect(notice).toHaveCount(0);
    expect(problems()).toEqual([]);
  } finally {
    // The switch is saved on the profile: leave the demo account on all contexts.
    const csrf = (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value ?? "";
    await page.request.patch("/api/v2/me/preferences/", {
      data: { active_context_id: null },
      headers: { "X-CSRFToken": csrf },
    });
  }
});
