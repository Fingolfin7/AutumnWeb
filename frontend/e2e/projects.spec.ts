import { expect, test } from "@playwright/test";
import { toasts, trackErrors } from "./helpers";

test("create a project, rename it, then delete it", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  // A retry must not collide with the project an earlier attempt created.
  const name = `Scratch ${testInfo.project.name} project ${testInfo.retry}.${testInfo.repeatEachIndex}`;
  const renamed = `${name} renamed`;

  await page.goto("/create_project/");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Description", { exact: true }).fill("Created by the e2e suite");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(toasts(page).getByText("Project created successfully")).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/$/);

  await page.goto(`/projects/?search=${encodeURIComponent(name)}`);
  await page.getByRole("link", { name, exact: true }).click();
  await expect(page).toHaveURL(/\/update_project\/\d+\/$/);
  /* The URL changes before the page renders: while its code loads, React
     Router keeps the list on screen. Wait for the form itself. */
  const nameField = page.getByLabel("Name", { exact: true });
  await expect(nameField).toHaveValue(name);
  await nameField.fill(renamed);
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
