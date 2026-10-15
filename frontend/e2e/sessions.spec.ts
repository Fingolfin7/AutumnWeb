import { expect, test } from "@playwright/test";
import { toasts, trackErrors } from "./helpers";

test("searching sessions narrows the list and the filter survives a reload", async ({ page }) => {
  const problems = trackErrors(page);
  await page.goto("/sessions/");
  const list = page.getByRole("region", { name: "Sessions" });
  await expect(list).toBeVisible();
  const total = await list.getByRole("listitem").count();
  expect(total).toBeGreaterThan(5);

  await page.getByRole("searchbox", { name: /Search projects, subprojects, and session notes/ }).fill("grammar");
  await page.getByRole("button", { name: "Search", exact: true }).click();

  await expect(page).toHaveURL(/[?&]search=grammar\b/);
  await expect(page.locator(".result-count")).not.toHaveText(String(total));
  const rows = list.getByRole("listitem");
  await expect.poll(() => rows.count()).toBeLessThan(total);
  expect(await rows.count()).toBeGreaterThan(0);
  for (const text of await rows.allInnerTexts()) expect(text.toLowerCase()).toContain("grammar");

  await page.reload();
  await expect(page).toHaveURL(/[?&]search=grammar\b/);
  await expect(page.getByRole("searchbox", { name: /Search projects/ })).toHaveValue("grammar");
  await expect(list.getByRole("listitem")).toHaveCount(await rows.count());
  expect(problems()).toEqual([]);
});

test("editing a session note saves it", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  const note = `Edited by the ${testInfo.project.name} e2e run`;

  await page.goto("/sessions/?search=Piano");
  const first = page.getByRole("region", { name: "Sessions" }).getByRole("listitem").first();
  await expect(first).toContainText("Piano Practice");
  await first.hover(); // desktop reveals the row actions on hover
  await first.getByRole("link", { name: "Edit session" }).click();

  await expect(page).toHaveURL(/\/update_session\/\d+\/$/);
  const field = page.getByRole("textbox", { name: "Note", exact: true });
  await field.fill(note);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(toasts(page).getByText("Updated session")).toBeVisible();

  await page.goto("/sessions/?search=Piano");
  await expect(page.getByRole("region", { name: "Sessions" }).getByText(note)).toBeVisible();
  expect(problems()).toEqual([]);
});
