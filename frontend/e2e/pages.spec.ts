import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

const PAGES = [
  "/", "/timers/", "/sessions/", "/projects/", "/review/", "/charts/", "/contexts/", "/tags/",
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

test("the shell keeps navigation, scroll and palette usable on both sizes", async ({ page }) => {
  await page.goto("/sessions/");
  const nav = page.getByRole("navigation", { name: "Primary", exact: true });
  await expect(nav.getByRole("link", { name: "Sessions", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "New timer", exact: true }).filter({ visible: true })).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await nav.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/$/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings", exact: true });
  await expect(settings.getByRole("link", { name: "Account & appearance" })).toHaveAttribute("href", "/profile/");
  await settings.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Go anywhere", exact: true }).click();
  const palette = page.getByRole("dialog", { name: "Go anywhere" });
  await palette.getByRole("textbox", { name: "Command" }).fill("Review");
  await palette.getByRole("button", { name: "Review", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Review", exact: true })).toHaveAttribute("aria-current", "page");
  await page.goto("/insights/");
  await expect(nav.getByRole("link", { name: "Review", exact: true })).toHaveAttribute("aria-current", "page");
});
