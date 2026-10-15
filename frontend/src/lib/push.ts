import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

/* Web Push for this browser (formerly window.AutumnPush in pwa.js). The
   server holds the subscriptions; the VAPID private key never leaves it. */

export type PushStatus = components["schemas"]["PushStatus"];

export function pushSupported(): boolean {
  return "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
}

export function pushStatus(): Promise<PushStatus> {
  return unwrap(api.GET("/api/v2/push/status/"));
}

export function decodeBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const invalid = "Autumn's Web Push public key is invalid. Check PUSH_VAPID_PUBLIC_KEY.";
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value) || value.length > 128) throw new Error(invalid);
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  let binary: string;
  try {
    binary = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  } catch {
    throw new Error(invalid);
  }
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  if (bytes.length !== 65 || bytes[0] !== 4) throw new Error(invalid);
  return bytes;
}

export function sameApplicationServerKey(existing: ArrayBuffer | null | undefined, expected: Uint8Array): boolean {
  if (!existing) return true;
  const bytes = new Uint8Array(existing);
  if (bytes.length !== expected.length) return false;
  return bytes.every((byte, index) => byte === expected[index]);
}

async function ensureSubscription(registration: ServiceWorkerRegistration, serverKey: Uint8Array<ArrayBuffer>) {
  const existing = await registration.pushManager.getSubscription();
  /* A subscription held under an older key re-registers happily and then
     fails every push with 403, so replace it. */
  if (existing && sameApplicationServerKey(existing.options?.applicationServerKey, serverKey)) return existing;
  if (existing) await existing.unsubscribe().catch(() => undefined);
  const subscribe = () => registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: serverKey });
  try {
    return await subscribe();
  } catch {
    /* A stale registration can make the first subscribe throw "push service
       error". Clear anything lingering and retry once. */
    const stale = await registration.pushManager.getSubscription();
    if (stale) await stale.unsubscribe().catch(() => undefined);
    return subscribe();
  }
}

export async function enablePush(): Promise<void> {
  if (!("Notification" in window)) throw new Error("This browser does not support notifications.");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    throw new Error("This browser does not support push notifications.");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(
      permission === "denied"
        ? "Notifications are blocked in this browser or for the browser app in system settings."
        : "Notification permission was not granted.",
    );
  }
  const status = await pushStatus();
  if (!status.available || !status.public_key) {
    throw new Error(status.configuration_error || "Browser push is not configured for this deployment.");
  }
  const registration = await navigator.serviceWorker.ready;
  const subscription = await ensureSubscription(registration, decodeBase64Url(status.public_key));
  await unwrap(
    api.POST("/api/v2/push/subscriptions/", { body: subscription.toJSON() as components["schemas"]["PushSubscriptionRequest"] }),
  );
}

export async function disablePush(): Promise<void> {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) return;
  await removeSubscription(subscription.endpoint);
  await subscription.unsubscribe();
}

/* DELETE names the device in its body. */
function removeSubscription(endpoint: string) {
  return unwrap(api.DELETE("/api/v2/push/subscriptions/", { body: { endpoint } }));
}

/** Queues a test notification; the dispatcher delivers it, so nothing is sent from the request. */
export function sendTestPush(): Promise<{ queued?: boolean; sent?: number }> {
  return unwrap(api.POST("/api/v2/push/test/"));
}

export type PermissionState = "loading" | "unavailable" | "denied" | "granted" | "default";

/** Where this browser stands, for the permission strip. */
export async function permissionState(): Promise<{ state: PermissionState; detail?: string; devices?: number }> {
  if (!pushSupported()) return { state: "unavailable", detail: "This browser does not support background notifications." };
  const [status, local] = await Promise.all([
    pushStatus(),
    navigator.serviceWorker.ready.then((r) => r.pushManager.getSubscription()).catch(() => null),
  ]);
  if (!status.available) {
    return { state: "unavailable", detail: status.configuration_error || "This deployment has not configured browser push yet." };
  }
  const permission = Notification.permission;
  if (permission === "denied") return { state: "denied" };
  if (permission === "granted" && local) return { state: "granted", devices: status.subscriptions };
  return { state: "default" };
}

/* Browser-thrown push failures (an AbortError reading "Registration failed -
   push service error") are only diagnosable with their name attached. */
export function describePushError(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback;
  const message = error.message || fallback;
  return error.name && error.name !== "Error" && error.name !== "ApiError" ? `${error.name}: ${message}` : message;
}
