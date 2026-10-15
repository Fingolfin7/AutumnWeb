import { expect, test } from "@playwright/test";
import { toasts, trackErrors } from "./helpers";

test("create a project, rename it, then delete it", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  const name = `Scratch ${testInfo.project.name} project`;
  const renamed = `${name} renamed`;

  await page.goto("/create_project/");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Description").fill("Created by the e2e suite");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(toasts(page).getByText("Project created successfully")).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/$/);

  await page.goto(`/projects/?search=${encodeURIComponent(name)}`);
  await page.getByRole("link", { name, exact: true }).click();
  await expect(page).toHaveURL(/\/update_project\/\d+\/$/);
  await page.getByLabel("Name").fill(renamed);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(toasts(page).getByText("Project updated successfully")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(renamed);

  await page.getByRole("link", { name: "Delete project" }).click();
  await expect(page).toHaveURL(/\/delete_project\/\d+\/$/);
  await page.getByRole("button", { name: "Delete project" }).click();
  await expect(toasts(page).getByText("Project deleted successfully")).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/$/);

  await page.goto(`/projects/?search=${encodeURIComponent(name)}`);
  await expect(page.getByRole("link", { name: renamed })).toHaveCount(0);
  expect(problems()).toEqual([]);
});
