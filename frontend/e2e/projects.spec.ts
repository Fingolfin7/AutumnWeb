import { expect, test } from "@playwright/test";
import { toasts, trackErrors } from "./helpers";

test("create a project, rename it, then delete it", async ({ page }, testInfo) => {
  const problems = trackErrors(page);
  // A retry must not collide with the project an earlier attempt created.
  const name = `Scratch ${testInfo.project.name} project ${testInfo.retry}.${testInfo.repeatEachIndex}`;
  const renamed = `${name} renamed`;

  await page.goto("/create_project/");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByText("Description (optional)", { exact: true }).click();
  await page.getByLabel("Description", { exact: true }).fill("Created by the e2e suite");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(toasts(page).getByText("Project created.", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/update_project\/\d+\/$/);

  await page.goto(`/projects/?search=${encodeURIComponent(name)}`);
  await page.getByRole("link", { name, exact: true }).click();
  await expect(page).toHaveURL(/\/update_project\/\d+\/$/);
  /* The URL changes before the page renders: while its code loads, React
     Router keeps the list on screen. Wait for the form itself. */
  await page.getByRole("button", { name: "Project actions", exact: true }).click();
  await page.getByRole("button", { name: "Edit project", exact: true }).click();
  const nameField = page.getByLabel("Name", { exact: true });
  await expect(nameField).toHaveValue(name);
  await nameField.fill(renamed);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(toasts(page).getByText("Project updated successfully")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(renamed);

  await page.getByRole("button", { name: "Project actions", exact: true }).click();
  await page.getByRole("button", { name: "Edit project", exact: true }).click();
  await page.getByRole("link", { name: "Delete project" }).click();
  await expect(page).toHaveURL(/\/delete_project\/\d+\/$/);
  await page.getByRole("button", { name: "Delete project" }).click();
  await expect(toasts(page).getByText("Project deleted successfully")).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/$/);

  await page.goto(`/projects/?search=${encodeURIComponent(name)}`);
  await expect(page.getByRole("link", { name: renamed })).toHaveCount(0);
  expect(problems()).toEqual([]);
});


test("project journal filters sessions by subproject", async ({ page }) => {
  await page.goto("/projects/");
  await page.getByRole("link", { name: "Garden Planner App", exact: true }).click();
  const filters = page.getByRole("group", { name: "Filter journal by subproject" });
  const response = page.waitForResponse(result => result.url().includes("/api/v2/sessions/") && result.url().includes("subproject_ids=") && result.request().method() === "GET");
  await filters.getByRole("button", { name: /^Backend/ }).click();
  const data = await (await response).json();
  expect(data.sessions.length).toBeGreaterThan(0);
  expect(data.sessions.every((session: { subproject_allocations: { name: string }[] }) => session.subproject_allocations.some(sub => sub.name === "Backend"))).toBe(true);
  await expect(page.locator(".project-journal .journal-entry")).toHaveCount(data.sessions.length);
  await expect(filters.getByRole("button", { name: /^Backend/ })).toHaveAttribute("aria-pressed", "true");
});
