import { expect, test as setup } from "@playwright/test";
import { DEMO_PASSWORD, DEMO_USERNAME, STORAGE_STATE } from "./constants";

setup("log in as the demo account", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Username").fill(DEMO_USERNAME);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  await page.context().storageState({ path: STORAGE_STATE });
});
