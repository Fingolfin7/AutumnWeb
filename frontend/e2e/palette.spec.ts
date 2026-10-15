import { expect, test } from "@playwright/test";
import { trackErrors } from "./helpers";

test("the command palette opens with Ctrl+K and navigates", async ({ page, isMobile }) => {
  test.skip(isMobile, "Ctrl+K is a keyboard shortcut; phones have no keyboard to press it on");
  const problems = trackErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeAttached();

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Go anywhere" });
  await expect(palette).toBeVisible();
  await palette.getByRole("textbox", { name: "Command" }).fill("charts");
  await palette.getByRole("option", { name: /Charts/ }).first().click();

  await expect(page).toHaveURL(/\/charts\/$/);
  await expect(palette).toBeHidden();
  expect(problems()).toEqual([]);
});
