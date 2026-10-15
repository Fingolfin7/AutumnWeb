import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

const PAGES = [
  "/", "/timers/", "/sessions/", "/projects/", "/charts/", "/contexts/", "/tags/",
  "/notifications/", "/review/weekly/", "/import/", "/export/", "/profile/", "/insights/",
];

test("every main page loads without page or console errors", async ({ page }) => {
  const problems = trackErrors(page);
  for (const path of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first(), path).toBeAttached();
    await expect(page.locator(".error-state"), path).toHaveCount(0);
    await page.waitForLoadState("networkidle");
  }
  expect(problems()).toEqual([]);
});
