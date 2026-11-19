import { expect, test } from "@playwright/test";
import { toasts, trackErrors } from "./helpers";

test("searching sessions narrows the list and the filter survives a reload", async ({ page }) => {
  const problems = trackErrors(page);
  await page.goto("/sessions/");
  const list = page.getByRole("region", { name: "Sessions" });
  await expect(list).toBeVisible();
  const total = await list.getByRole("listitem").count();
  expect(total).toBeGreaterThan(5);

  const search = page.getByRole("searchbox", { name: /Search projects, subprojects, and session notes/ });
  await search.fill("grammar");
  await search.press("Enter");

  await expect(page).toHaveURL(/[?&]search=grammar\b/);
  await expect(page.locator(".result-count")).not.toHaveText(String(total));
  const rows = list.getByRole("listitem");
  /* The list empties while the search runs: wait until it holds only
     matches, at least one and fewer than before. */
  await expect
    .poll(async () => {
      const texts = await rows.allInnerTexts();
      return texts.length > 0 && texts.length < total && texts.every((text) => text.toLowerCase().includes("grammar"));
    })
    .toBe(true);
  const matches = await rows.count();

  await page.reload();
  await expect(page).toHaveURL(/[?&]search=grammar\b/);
  await expect(page.getByRole("searchbox", { name: /Search projects/ })).toHaveValue("grammar");
  await expect(list.getByRole("listitem")).toHaveCount(matches);
  expect(problems()).toEqual([]);
});

test("editing a session note in place saves it", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  // Each attempt writes a new note, or a retry would have nothing to save.
  const note = `Edited by the ${testInfo.project.name} e2e run ${testInfo.retry}.${testInfo.repeatEachIndex}`;

  await page.goto("/sessions/?search=Piano");
  const first = page.getByRole("region", { name: "Sessions" }).getByRole("listitem").first();
  await expect(first).toContainText("Piano Practice");
  await first.hover(); // desktop reveals the row actions on hover; a phone shows "…"
  await first.getByRole("button", { name: "Session actions" }).click();
  await page.getByRole("dialog", { name: "Session actions" }).getByRole("button", { name: "Edit note" }).click();
  await first.getByRole("textbox").fill(note);
  await first.getByRole("button", { name: "Save note" }).click();
  await expect(toasts(page).getByText("Note saved.")).toBeVisible();
  await expect(first.getByText(note)).toBeVisible();

  // The server has it (a reload may first show this device's saved copy).
  const id = (await first.getAttribute("id"))!.replace("session-", "");
  const saved = await page.request.get(`/api/v2/sessions/${id}?include=note`);
  expect((await saved.json()).note).toBe(note);
  expect(problems()).toEqual([]);
});
