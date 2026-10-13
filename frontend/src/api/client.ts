import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";
import { csrfToken } from "@/lib/csrf";
import { ApiError, toApiError } from "./errors";

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const sessionAuth: Middleware = {
  onRequest({ request }) {
    request.headers.set("X-Requested-With", "XMLHttpRequest");
    if (UNSAFE.has(request.method)) request.headers.set("X-CSRFToken", csrfToken());
    return request;
  },
  onResponse({ response }) {
    /* A session that expired mid-use: send the user through login and back. */
    if (response.status === 401 || (response.redirected && response.url.includes("/login"))) {
      redirectToLogin();
    }
    return response;
  },
};

export function redirectToLogin() {
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login/?next=${encodeURIComponent(next)}`);
}

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(sessionAuth);

/* openapi-fetch resolves to {data, error, response}; every caller here wants
   the data or a thrown ApiError, so TanStack Query sees failures as failures. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await promise;
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  const { data, error, response } = result;
  if (!response.ok) throw toApiError(response.status, error);
  return data as T;
}

/* For endpoints that are not (yet) in the OpenAPI schema. */
export async function requestJson<T>(
  method: string,
  url: string,
  body?: unknown,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "XMLHttpRequest");
  headers.set("Accept", "application/json");
  if (body !== undefined && !(body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (UNSAFE.has(method)) headers.set("X-CSRFToken", csrfToken());
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(0, "network", "Can't reach Autumn. Check your connection.", cause);
  }
  if (response.status === 401) redirectToLogin();
  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }
  if (!response.ok) throw toApiError(response.status, parsed);
  return parsed as T;
}
