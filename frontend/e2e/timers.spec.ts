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

  await expect(page).toHaveURL(/\/$/);
  const card = page.getByRole("article", { name: "Running timer: Garden Planner App" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Running", { exact: true })).toBeVisible();
  if (testInfo.project.name === "phone") {
    const headerHeight = await card.evaluate((element) => element.querySelector(".timer-note-editor")!.getBoundingClientRect().top - element.getBoundingClientRect().top);
    expect(headerHeight).toBeLessThanOrEqual(180);
    await expect(page.locator(".timer-dock")).toBeHidden();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.locator(".timer-dock")).toBeVisible();
    await card.scrollIntoViewIfNeeded();
    await expect(page.locator(".timer-dock")).toBeHidden();
  }

  await page.goto("/");
  await expect(page.getByRole("article", { name: "Running timer: Garden Planner App" })).toBeVisible();

  await page.goto("/timers/");
  const runningCard = page.getByRole("article", { name: "Running timer: Garden Planner App" });
  await runningCard.getByRole("button", { name: "Edit session note", exact: true }).click();
  const writer = page.getByRole("dialog", { name: "Full-screen note writer" });
  // A phone goes straight to the writer; a desktop edits in place and can expand.
  if (testInfo.project.name === "phone") {
    await writer.getByRole("textbox", { name: "Session note" }).fill(note);
  } else {
    await runningCard.getByRole("textbox", { name: "Session note" }).fill(note);
    await runningCard.getByRole("button", { name: "Expand note" }).click();
    await expect(writer.getByRole("textbox", { name: "Session note" })).toHaveValue(note);
  }
  await writer.getByRole("button", { name: "Done" }).click();
  await expect(runningCard.locator(".timer-note-editor")).toContainText(note);
  const stoppedId = await runningCard.getAttribute("data-timer-id");
  await expect.poll(async () => (await (await page.request.get(`/api/v2/sessions/${stoppedId}?include=note`)).json()).note).toBe(note);
  await runningCard.getByRole("link", { name: "Stop" }).click();
  await expect(page).toHaveURL(/\/stop_timer\/\d+\/$/);
  await expect(page.getByRole("textbox", { name: "Note", exact: true })).toHaveValue(note);
  await page.getByText("Adjust times & allocation", { exact: true }).click();
  const savedBeforeDone = await page.request.get(`/api/v2/sessions/${stoppedId}?include=note`);
  // The session was saved by the first Stop action; Done only edits the journal.
  expect(savedBeforeDone.ok()).toBeTruthy();
  expect((await savedBeforeDone.json()).active).toBe(false);
  const end = page.locator("#id_end_time");
  const initialEnd = await end.inputValue();
  const duration = page.locator(".timer-duration");
  const initialDuration = await duration.textContent();
  await page.waitForTimeout(2_000);
  await expect(end).toHaveValue(initialEnd);
  await expect(duration).toHaveText(initialDuration!);
  await page.getByRole("button", { name: "Done", exact: true }).click();

  await expect(page).toHaveURL(/\/$/);
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

  test("a timer started offline is saved, then synced when the connection returns", async ({ page, context }, testInfo) => {
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
    await expect(page.getByRole("combobox", { name: "Project", exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2_500); // the query cache is persisted on a throttle

    await context.setOffline(true);
    await expect(page.locator(".offline-banner")).toBeVisible();
    await pickProject(page, "Piano Practice");
    await page.getByRole("button", { name: "Start timer" }).click();

    const card = page.getByRole("article", { name: "Running timer: Piano Practice" });
    await expect(card).toBeVisible();
    await expect(card.getByText("Running · saved offline")).toBeVisible();

    await card.getByRole("button", { name: "Edit session note", exact: true }).click();
    const offlineWriter = page.getByRole("dialog", { name: "Full-screen note writer" });
    if (testInfo.project.name === "phone") {
      await offlineWriter.getByRole("textbox", { name: "Session note" }).fill("A journal started offline.");
    } else {
      await card.getByRole("textbox", { name: "Session note" }).fill("A journal started offline.");
      await card.getByRole("button", { name: "Expand note", exact: true }).click();
    }
    await expect(offlineWriter.getByRole("status")).toHaveText("Draft kept on this device");
    await offlineWriter.getByRole("button", { name: "Done", exact: true }).click();
    await expect(offlineWriter).toHaveCount(0);
    await context.setOffline(false);
    await expect(toasts(page).getByText(/Synced 1 offline change/)).toBeVisible({ timeout: 30_000 });
    await expect(card.getByText("Running · saved offline")).toHaveCount(0);
    await expect(card.getByText("Running", { exact: true })).toBeVisible();
    await expect(card.locator(".timer-note-editor")).toContainText("A journal started offline.");
    const id = await card.getAttribute("data-timer-id");
    await expect.poll(async () => (await (await page.request.get(`/api/v2/sessions/${id}?include=note`)).json()).note).toBe("A journal started offline.");
    await page.reload();
    await expect(card.locator(".timer-note-editor")).toContainText("A journal started offline.");
  });

  test("an offline stop keeps its note and syncs the original session", async ({ page, context }) => {
    await page.goto("/start_timer/");
    await pickProject(page, "Piano Practice");
    await page.getByRole("button", { name: "Start timer", exact: true }).click();
    const card = page.getByRole("article", { name: "Running timer: Piano Practice" });
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-timer-id", /^\d+$/);
    const id = await card.getAttribute("data-timer-id");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForTimeout(2500);
    await context.setOffline(true);
    await card.getByRole("link", { name: "Stop", exact: true }).click();
    const note = page.getByRole("textbox", { name: "Note", exact: true });
    await note.fill("Offline reflection, saved before the stop is queued.");
    await page.getByRole("button", { name: "Stop timer", exact: true }).click();
    await expect(card).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/);
    await context.setOffline(false);
    await expect(toasts(page).getByText(/Synced 1 offline change/)).toBeVisible({ timeout: 30000 });
    const response = await page.request.get(`/api/v2/sessions/${id}?include=note`);
    expect(response.ok()).toBeTruthy();
    const saved = await response.json();
    expect(saved.active).toBe(false);
    expect(saved.note).toBe("Offline reflection, saved before the stop is queued.");
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

    await expect(page).toHaveURL(/\/$/);
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


test("Undo stop resumes the same session from its original start", async ({ page }) => {
  await page.goto("/start_timer/");
  await pickProject(page, "Piano Practice");
  await page.getByRole("button", { name: "Start timer", exact: true }).click();
  const card = page.getByRole("article", { name: "Running timer: Piano Practice" });
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-timer-id", /^\d+$/);
  const id = await card.getAttribute("data-timer-id");
  const original = await (await page.request.get(`/api/v2/sessions/${id}`)).json();
  await card.getByRole("link", { name: "Stop", exact: true }).click();
  await expect(page.getByRole("button", { name: "Done", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Undo stop", exact: true }).click();
  await expect(card).toBeVisible();
  const resumed = await (await page.request.get(`/api/v2/sessions/${id}`)).json();
  expect(resumed.uuid).toBe(original.uuid);
  expect(resumed.start).toBe(original.start);
  expect(resumed.active).toBe(true);
});
