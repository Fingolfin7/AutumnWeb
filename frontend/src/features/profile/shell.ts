import { bootstrap } from "@/bootstrap";
import type { Prefs } from "./model";

/* The app shell (header avatar, page backdrop, header dimming slider) is
   rendered from the bootstrap blob at page load. When the profile changes
   them, bring the live page and the cached bootstrap along so no reload is
   needed. */

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
