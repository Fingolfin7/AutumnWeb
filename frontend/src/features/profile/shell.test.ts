import { EMPTY_BOOTSTRAP } from "@/bootstrap";
import { applyMe } from "./shell";

it("takes the server's chart defaults and key state into the bootstrap profile", () => {
  const profile = { ...EMPTY_BOOTSTRAP.profile };
  applyMe(profile, {
    api_version: 2,
    capabilities: [],
    user: { id: 1, username: "finrod", timezone: "UTC" },
    default_chart_start_date: "2026-09-15",
    default_chart_end_date: "2026-10-15",
    openai_key_configured: true,
  });
  expect(profile).toMatchObject({
    default_chart_start_date: "2026-09-15",
    default_chart_end_date: "2026-10-15",
    openai_key_configured: true,
  });
  expect(profile.timezone).toBe(EMPTY_BOOTSTRAP.profile.timezone);
});
