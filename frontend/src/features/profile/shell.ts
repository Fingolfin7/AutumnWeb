import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { bootstrap, type Bootstrap } from "@/bootstrap";
import type { Prefs } from "./model";

/* The app shell (header avatar, page backdrop, header dimming slider) is
   rendered from the bootstrap blob at page load. When the profile changes
   them, bring the live page and the cached bootstrap along so no reload is
   needed. */

/* The Charts page opens on profile.default_chart_start/end_date and Charts and
   Insights offer related search when profile.openai_key_configured (all from
   the bootstrap blob). After the profile changes a default filter or an API
   key, take the server's current values from GET /api/v2/me/. */
export function applyMe(profile: Bootstrap["profile"], me: components["schemas"]["Me"]) {
  profile.default_chart_start_date = me.default_chart_start_date;
  profile.default_chart_end_date = me.default_chart_end_date;
  profile.openai_key_configured = me.openai_key_configured;
}

/* The rest of the profile the app reads from the bootstrap, straight from a
   fresh preferences response. */
export function applyPrefs(
  fresh: Pick<Prefs, "timezone" | "default_chart_project_count" | "ai_features_enabled" | "related_similarity">,
) {
  const profile = bootstrap().profile;
  profile.related_similarity = fresh.related_similarity;
  profile.timezone = fresh.timezone;
  profile.default_chart_project_count = fresh.default_chart_project_count;
  profile.ai_features_enabled = fresh.ai_features_enabled;
}

export async function refreshBootstrapProfile(): Promise<void> {
  applyMe(bootstrap().profile, await unwrap(api.GET("/api/v2/me/")));
}

export function applyAvatar(url: string) {
  bootstrap().profile.avatar_url = url;
  const img = document.querySelector<HTMLImageElement>(".app-header .avatar img");
  if (img) img.src = url;
}

export function applyDimming(value: number) {
  document.body.style.setProperty("--background-dim-opacity", (value / 100).toFixed(2));
}

/* The header slider is an uncontrolled-looking React input; set it through the
   native setter and fire `input` so its own state follows. That also repeats
   its (harmless) save of the same value. */
export function syncHeaderDimming(value: number) {
  bootstrap().profile.background_dimming = value;
  const input = document.getElementById("header-dimming") as HTMLInputElement | null;
  if (!input || Number(input.value) === value) return;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, String(value));
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

export function applyBackground(background: Prefs["background"]) {
  const body = document.body;
  const url = background.image_url;
  // A video rendered with the original page would otherwise cover the new image.
  if (body.dataset.bgUrl !== (url ?? "")) document.querySelector(".workspace-bg-video")?.remove();
  if (url) {
    body.classList.add("bg-active");
    body.style.setProperty("--workspace-bg-image", `url('${url}')`);
    body.dataset.bgUrl = url;
  } else {
    body.classList.remove("bg-active");
    body.style.removeProperty("--workspace-bg-image");
    delete body.dataset.bgUrl;
  }
}
