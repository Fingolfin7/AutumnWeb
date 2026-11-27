import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

test("downloads a backup, previews a missing project, and restores it", async ({ page }, info) => {
  const problems = trackErrors(page);
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === "csrftoken")!.value;
  const headers = { "X-CSRFToken": csrf };
  const name = `Backup example ${info.project.name} ${info.retry}`;
  const project = await page.request.post("/api/v2/projects/", { headers, data: { name } });
  expect(project.ok(), await project.text()).toBeTruthy();
  const { id, version } = await project.json();

  await page.goto("/settings/backup/");
  await expect(page.getByRole("heading", { name: "Backup & restore" })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download backup" }).click();
  const archive = await download;
  const filename = (await archive.path())!;
  const deleted = await page.request.delete(`/api/v2/projects/${id}`, {
    headers: { ...headers, "If-Match": String(version) },
  });
  expect(deleted.ok(), await deleted.text()).toBeTruthy();

  const file = page.locator("input[type=file]");
  await file.setInputFiles(filename);
  await expect(page.getByText("Restoring adds 1 record", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await page.getByRole("dialog", { name: /Restore into/ }).getByRole("button", { name: "Restore" }).click();
  await expect(page.getByText("Restored 1 record into", { exact: false }).first()).toBeVisible();

  await file.setInputFiles(filename);
  await expect(page.getByText("Everything in this backup is already in this account.")).toBeVisible();
  expect(problems()).toEqual([]);
});
