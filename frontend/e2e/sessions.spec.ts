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

test("editing a session note saves it", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  // Each attempt writes a new note, or a retry would have nothing to save.
  const note = `Edited by the ${testInfo.project.name} e2e run ${testInfo.retry}.${testInfo.repeatEachIndex}`;

  await page.goto("/sessions/?search=Piano");
  const first = page.getByRole("region", { name: "Sessions" }).getByRole("listitem").first();
  await expect(first).toContainText("Piano Practice");
  if (testInfo.project.name === "phone") {
    const heading = first.locator(".journal-heading");
    await heading.scrollIntoViewIfNeeded();
    const box = (await heading.boundingBox())!;
    const touch = await page.context().newCDPSession(page);
    const y = box.y + 22;
    await touch.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x + box.width - 30, y }] });
    for (let i = 1; i <= 8; i++) await touch.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: box.x + box.width - 30 - i * 20, y }] });
    await touch.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await touch.detach();
    await page.getByRole("dialog", { name: "Session actions" }).getByRole("button", { name: "Edit note", exact: true }).tap();
  } else {
    await first.getByRole("button", { name: "Edit note", exact: true }).click();
  }

  await expect(page).toHaveURL(/\/sessions\/\?search=Piano/);
  const field = page.getByRole("textbox", { name: "Note", exact: true });
  await field.fill(note);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(toasts(page).getByText("Note saved.", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("region", { name: "Sessions" }).getByText(note)).toBeVisible();
  expect(problems()).toEqual([]);
});
