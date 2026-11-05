import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

test("Review preserves old links, applies filters immediately and offers every chart", async ({ page }) => {
  const problems = trackErrors(page);
  await page.goto("/charts/?chart_type=heatmap&start_date=2026-01-01&end_date=2026-12-31");
  await expect(page).toHaveURL(/\/review\/\?chart_type=heatmap/);
  await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Filters/ }).click();
  await page.getByLabel("Search projects, subprojects, and session notes").fill("unlikely-review-empty-term");
  await expect(page).toHaveURL(/search=unlikely-review-empty-term/);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.locator(".review-projects")).toContainText("No completed sessions");
  await expect(page.getByRole("button", { name: "Choose chart" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await page.getByRole("button", { name: "Choose chart" }).click();
  const chooser = page.getByRole("dialog", { name: "Choose a chart" });
  await expect(chooser.locator(".review-chart-choice")).toHaveCount(9);
  await chooser.getByText("More ways to look", { exact: true }).click();
  await chooser.getByRole("button", { name: /Ranked project bars/ }).click();
  await expect(page.locator(".review-project-row").first()).toBeVisible();
  await page.getByRole("radio", { name: "Custom", exact: true }).check();
  await page.getByLabel("Start date", { exact: true }).fill("2026-01-01");
  await page.getByLabel("End date", { exact: true }).fill("2026-12-31");
  await page.getByRole("button", { name: "Done", exact: true }).click();

  await page.getByRole("radio", { name: "Year of embers", exact: true }).check();
  await expect(page.locator(".ember-month")).toHaveCount(12);
  await page.locator(".ember-month").first().click();
  await expect(page.getByRole("radio", { name: "Period", exact: true })).toBeChecked();
  await page.goto("/review/weekly/?week=2026-10-05");
  await expect(page).toHaveURL(/\/review\/\?start_date=2026-10-05&end_date=2026-10-11/);
  expect(problems()).toEqual([]);
});
