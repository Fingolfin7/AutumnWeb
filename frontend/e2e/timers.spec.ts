import { expect, test } from "@playwright/test";
import { buildSavedOffline, discardTimers, pickProject, toasts, trackErrors } from "./helpers";

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
  const runningCard = page.getByRole("article", { name: "Running timer: Garden Planner App" });
  await runningCard.getByRole("textbox", { name: "Session note" }).fill(note);
  await runningCard.getByRole("link", { name: "Stop" }).click();
  await expect(page).toHaveURL(/\/stop_timer\/\d+\/$/);
  await expect(page.getByRole("textbox", { name: "Note", exact: true })).toHaveValue(note);
  const end = page.locator("#id_end_time");
  const initialEnd = await end.inputValue();
  const duration = page.locator(".timer-duration");
  const initialDuration = await duration.textContent();
  await page.waitForTimeout(2_000);
  await expect(end).toHaveValue(initialEnd);
  await expect(duration).toHaveText(initialDuration!);
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

test("log a past session from the Timers page and find it on Sessions", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  const note = `Logged after the fact ${testInfo.project.name} ${testInfo.retry}.${testInfo.repeatEachIndex}

Second paragraph.`;

  await page.goto("/timers/");
  await page.getByRole("link", { name: "Log past session" }).click();
  await expect(page).toHaveURL(/\/start_timer\/\?mode=log$/);
  await pickProject(page, "Piano Practice");
  await page.getByRole("button", { name: "45m" }).click();
  await expect(page.getByRole("status").filter({ hasText: "logged" })).toHaveText("45 minutes logged");
  await page.getByRole("textbox", { name: "Note", exact: true }).fill(note);
  await page.getByRole("button", { name: "Log session" }).click();

  await expect(page).toHaveURL(/\/sessions\/\?start_date=/);
  await expect(toasts(page).getByText("Logged 45 minutes of Piano Practice.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Sessions" }).getByText("Second paragraph.").first()).toBeVisible();
  expect(problems()).toEqual([]);
});

test.describe("offline", () => {
  test.use({ serviceWorkers: "allow" });

  test("a timer started offline is saved, then synced when the connection returns", async ({ page, context }) => {
    // Load the app online so the service worker, the build and the project list are cached.
    await page.goto("/timers/");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload();
    await buildSavedOffline(page);
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

  test("a project created offline can take a timer before it syncs, and syncs once", async ({ page, context }, testInfo) => {
    const name = `Bouldering ${testInfo.project.name} ${testInfo.retry}.${testInfo.repeatEachIndex}`;
    await page.goto("/create_project/");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload();
    await buildSavedOffline(page);
    await page.waitForLoadState("networkidle");

    await context.setOffline(true);
    await page.getByLabel("Name").fill(name);
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page).toHaveURL(/\/projects\/$/);
    await expect(toasts(page).getByText(`Saved ${name} on this device.`, { exact: false })).toBeVisible();
    const band = page.locator(".band", { hasText: name });
    await expect(band.getByText("Saved offline · waiting to sync")).toBeVisible();

    await band.getByRole("button", { name: `Start a timer on ${name}` }).click();
    await page.getByRole("link", { name: "Timers" }).first().click();
    const card = page.getByRole("article", { name: `Running timer: ${name}` });
    await expect(card.getByText("Running · saved offline")).toBeVisible();

    await context.setOffline(false);
    await expect(toasts(page).getByText(/Synced 2 offline changes/)).toBeVisible({ timeout: 30_000 });
    await expect(card.getByText("Running", { exact: true })).toBeVisible();
    const listed = (await (await page.request.get("/api/v2/projects/?limit=500")).json()) as { projects: { id: number; name: string }[] };
    const created = listed.projects.filter((project) => project.name === name);
    expect(created).toHaveLength(1);
    const timers = (await (await page.request.get("/api/v2/timers/")).json()) as { timers: { project: { id: number } }[] };
    expect(timers.timers.map((timer) => timer.project.id)).toEqual([created[0]!.id]);
  });
  test("a session logged offline is listed on Sessions as waiting, then syncs", async ({ page, context }, testInfo) => {
    const note = `Logged with no signal ${testInfo.project.name} ${testInfo.retry}.${testInfo.repeatEachIndex}`;
    // Online first, so the pages used below, the timers and the session list are saved on the device.
    await page.goto("/timers/");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload();
    await buildSavedOffline(page);
    await page.getByRole("link", { name: "Sessions" }).first().click();
    await expect(page.getByRole("region", { name: "Sessions" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2_500); // the query cache is persisted on a throttle

    await context.setOffline(true);
    await page.getByRole("link", { name: "Timers" }).first().click();
    await page.getByRole("link", { name: "Log past session" }).click();
    await pickProject(page, "Piano Practice");
    await page.getByRole("button", { name: "45m" }).click();
    await page.getByRole("textbox", { name: "Note", exact: true }).fill(note);
    await page.getByRole("button", { name: "Log session" }).click();
    await expect(toasts(page).getByText(/Saved 45 minutes of Piano Practice on this device/)).toBeVisible();

    await page.getByRole("link", { name: "Sessions" }).first().click();
    const row = page.locator(".band", { hasText: note });
    await expect(row.getByText("Saved offline · waiting to sync")).toBeVisible();

    await context.setOffline(false);
    await expect(toasts(page).getByText(/Synced 1 offline change/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Saved offline · waiting to sync")).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Sessions" }).getByText(note).first()).toBeVisible();
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
