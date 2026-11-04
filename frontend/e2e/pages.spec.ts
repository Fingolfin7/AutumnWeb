import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

const PAGES = [
  "/", "/timers/", "/sessions/", "/projects/", "/review/", "/charts/", "/contexts/", "/tags/",
  "/settings/", "/settings/account/", "/settings/ai/", "/notifications/", "/review/weekly/", "/import/", "/export/", "/profile/", "/insights/",
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
  await expect(settings.getByRole("link", { name: "Account & appearance" })).toHaveAttribute("href", "/settings/account/");
  await settings.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Go anywhere", exact: true }).click();
  const palette = page.getByRole("dialog", { name: "Go anywhere" });
  await palette.getByRole("textbox", { name: "Command" }).fill("Review");
  await palette.getByRole("button", { name: "Review", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Review", exact: true })).toHaveAttribute("aria-current", "page");
  await page.goto("/insights/");
  await expect(nav.getByRole("link", { name: "Review", exact: true })).toHaveAttribute("aria-current", "page");
});

test("Settings keeps bookmarks, swatches and import streaming usable", async ({ page }) => {
  const problems = trackErrors(page);
  await page.goto("/profile/");
  await expect(page).toHaveURL(/\/settings\/account\/$/);
  const firstName = `Settings ${Date.now()}`;
  await page.getByLabel("First name", { exact: true }).fill(firstName);
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("status", { name: "" }).filter({ hasText: "All changes saved" })).toBeVisible();
  expect((await (await page.request.get("/api/v2/me/account/")).json()).first_name).toBe(firstName);
  await page.goto("/tags/");
  await expect(page).toHaveURL(/\/settings\/tags\/$/);
  const name = `Settings swatch ${Date.now()}`;
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByRole("radio", { name: "Lilac", exact: true }).check();
  await page.getByRole("button", { name: "Create tag", exact: true }).click();
  const tagLink = page.getByRole("link", { name, exact: true });
  await expect(tagLink).toBeVisible();
  await tagLink.click();
  await expect(page.getByLabel("Color", { exact: true })).toHaveValue("#a78bca");

  // Export the fictional fixture and re-import it: duplicates must remain safe.
  const exported = await page.request.get("/api/v2/export/?export_format=2");
  expect(exported.ok()).toBeTruthy();
  await page.goto("/import/");
  await expect(page).toHaveURL(/\/settings\/import\/$/);
  await page.getByLabel("JSON file", { exact: true }).setInputFiles({ name: "autumn.json", mimeType: "application/json", buffer: Buffer.from(await exported.text()) });
  await expect(page.getByRole("region", { name: "Import preview" })).toBeVisible();
  await expect(page.getByText("Add project", { exact: true })).toHaveCount(0);
  const stream = page.waitForResponse((response) => response.url().includes("/stream/") && response.ok());
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await stream;
  await expect(page.getByRole("progressbar", { name: "Import progress" })).toHaveAttribute("aria-valuenow", "100");
  expect(problems()).toEqual([]);
});
