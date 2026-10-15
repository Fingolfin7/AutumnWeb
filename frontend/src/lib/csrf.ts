import { bootstrap } from "@/bootstrap";

/* Django rotates the token on login; the cookie is the freshest source, the
   bootstrap blob the fallback when cookies are HttpOnly. */
export function csrfToken(): string {
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("csrftoken="));
  if (match) return decodeURIComponent(match.slice("csrftoken=".length));
  return bootstrap().csrf_token;
}
