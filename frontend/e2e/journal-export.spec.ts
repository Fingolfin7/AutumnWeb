import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("downloads all filtered sessions without expanding the journal", async ({ page }) => {
  const end = new Date();
  end.setUTCDate(end.getUTCDate() - 2);
  const endDate = end.toISOString().slice(0, 10);
  const filter = `end_date=${endDate}`;
  const response = await page.request.get(`/api/v2/sessions/?${filter}&limit=1`);
  const { total } = await response.json();
  expect(total).toBeGreaterThan(30);

  await page.goto(`/sessions/?context=all&${filter}`);
  const rows = page.getByRole("region", { name: "Sessions", exact: true }).getByRole("listitem");
  await expect(rows).toHaveCount(30);
  await expect(page.getByRole("button", { name: `Copy ${total.toLocaleString()} sessions as Markdown` })).toBeEnabled();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download .md", exact: true }).click();
  const file = await downloaded;
  const markdown = await readFile((await file.path())!, "utf-8");
  expect(file.suggestedFilename()).toBe("autumn-sessions.md");
  expect(markdown.match(/^### /gm)).toHaveLength(total);
  expect(markdown).toMatch(/^## \d{4}-\d{2}-\d{2}$/m);
  expect(markdown).toMatch(/^> \S/m);
  await expect(rows).toHaveCount(30);
});

test("opens weekly project notes and offers the complete Markdown when clipboard access is blocked", async ({ page }) => {
  await page.addInitScript(() => {
    const refuse = () => Promise.reject(new DOMException("Clipboard permission denied", "NotAllowedError"));
    Object.defineProperty(navigator, "clipboard", { value: { write: refuse, writeText: refuse } });
  });
  const response = await page.request.get("/api/v2/reports/weekly-review/");
  const { per_project: projects, session_count: total } = await response.json() as {
    per_project: { project_name: string }[];
    session_count: number;
  };
  expect(projects.length).toBeGreaterThan(1);

  await page.goto("/review/weekly/");
  const project = page.getByRole("article").filter({ has: page.getByRole("link", { name: projects[0]!.project_name, exact: true }) });
  const notes = project.locator(".nx-review-notes-list");
  await expect(notes).toHaveCount(0);
  await project.getByText("Session notes", { exact: true }).click();
  await expect(notes.getByRole("link").first()).toHaveText(/\w{3} \d{1,2} \w{3}, \d{2}:\d{2}/);
  await expect(notes.locator(".session-note-body").first()).toBeVisible();

  await page.getByRole("button", { name: "Copy week as Markdown" }).click();
  const dialog = page.getByRole("dialog", { name: "Copy Markdown" });
  const text = dialog.getByRole("textbox", { name: "Markdown" });
  await expect(text).toBeVisible();
  const markdown = await text.inputValue();
  expect(markdown.match(/^### /gm)).toHaveLength(total);
  for (const { project_name: name } of projects) expect(markdown).toContain(`## ${name}\n`);
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).toHaveCount(0);
});
