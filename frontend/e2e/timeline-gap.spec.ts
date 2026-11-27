import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

test.use({ serviceWorkers: "block" });

test("fill part of a timeline gap and pick up the new note on that project", async ({ page }, info) => {
  const problems = trackErrors(page);
  // A fixed historical day makes this work at midnight too. Home receives
  // that day's real timeline from Django, including after the form saves.
  const day = `2004-11-${String((info.project.name === "phone" ? 14 : 1) + info.retry).padStart(2, "0")}`;
  const timelineUrl = `/api/v2/reports/timeline/?start=${day}&end=${day}`;
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === "csrftoken")!.value;
  const headers = { "X-CSRFToken": csrf };
  const create = async (name: string) => {
    const res = await page.request.post("/api/v2/projects/", { headers, data: { name } });
    expect(res.ok(), await res.text()).toBeTruthy();
    return (await res.json()).id as number;
  };
  const projectName = `Review work ${day}`;
  const edges = await create(`Surrounding work ${day}`);
  const projectId = await create(projectName);
  for (const [start, end] of [["09:00", "09:45"], ["10:20", "11:00"]]) {
    const res = await page.request.post("/api/v2/sessions/", { headers, data: {
      project_id: edges, start: `${day}T${start}:11Z`, end: `${day}T${end}:11Z`,
    } });
    expect(res.ok(), await res.text()).toBeTruthy();
  }
  const timeline = async () => (await page.request.get(timelineUrl)).json();
  await page.route("**/api/v2/dashboard/**", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), timeline: await timeline() } });
  });
  await page.route("**/api/v2/reports/timeline/**", async route => {
    await route.fulfill({ json: await timeline() });
  });
  await page.goto("/");
  await page.getByRole("link", { name: /Log .*35m untracked/i }).click();
  await expect(page.getByLabel("Start time")).toHaveValue(day + "T09:45:11");
  await expect(page.getByLabel("End time")).toHaveValue(day + "T10:20:11");
  await page.getByLabel("End time").fill(day + "T10:10:11");
  const projectField = page.getByRole("combobox", { name: "Project" });
  await projectField.fill(projectName);
  await expect(page.getByRole("option", { name: projectName })).toBeVisible();
  await projectField.press("Enter");
  const note = "Recheck the diagrams after the next import.";
  await page.getByRole("textbox", { name: "Note", exact: true }).fill(note);
  await page.getByRole("button", { name: "Log session" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: /Log .*10m untracked/i })).toBeVisible();
  await page.goto(`/start_timer/?project_id=${projectId}`);
  await expect(page.getByText(note, { exact: true })).toBeVisible();
  await page.goto(`/update_project/${projectId}/`);
  await expect(page.getByText(note, { exact: true })).toBeVisible();
  expect(problems()).toEqual([]);
});
