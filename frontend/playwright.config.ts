import { defineConfig, devices } from "@playwright/test";
import { STORAGE_STATE } from "./e2e/constants";

/* End-to-end suite against the BUILT app served by Django on a throwaway
   SQLite database (see e2e/server.mjs). Run it with `npm run e2e`; set
   PYTHON to the interpreter that has the project's requirements installed. */
const port = Number(process.env.E2E_PORT ?? 8799);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "test-results",
  // One shared database, so tests must not run side by side.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 7_500 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "node e2e/server.mjs",
    url: `${baseURL}/healthz/`,
    // Never adopt a server someone left running: it could be on another database.
    reuseExistingServer: false,
    timeout: 240_000,
    stdout: "ignore", // Django logs every request; startup output and errors still show
    stderr: "pipe",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "desktop",
      testIgnore: /auth\.setup\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        storageState: STORAGE_STATE,
      },
    },
    {
      name: "phone",
      testIgnore: /auth\.setup\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
        storageState: STORAGE_STATE,
      },
    },
  ],
});
