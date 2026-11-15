import { useEffect, useSyncExternalStore } from "react";
import { useRouteError } from "react-router";
import { useOnline } from "@/lib/useOnline";
import { isUnreachable, subscribeUnreachable } from "./savedData";
import { setPageTitle } from "./title";

/** A page's code couldn't be fetched: opened with no connection before the
    service worker had saved it, or a deploy replaced the build this tab runs. */
export class PageLoadError extends Error {}

const RELOADED = "autumn:page-reloaded";

/* A failed page load can't be retried in place, so the retry is a reload:
   once by itself as soon as Autumn is reachable, after that by the button. */
function reloadOnce() {
  try {
    if (Date.now() - Number(window.sessionStorage.getItem(RELOADED)) < 15_000) return;
    window.sessionStorage.setItem(RELOADED, String(Date.now()));
  } catch {
    return;
  }
  window.location.reload();
}

/** Shown in place of a page that failed to load or crashed while rendering. */
export function PageError() {
  const error = useRouteError();
  const online = useOnline();
  const unreachable = useSyncExternalStore(subscribeUnreachable, isUnreachable);
  const offline = !online || unreachable;
  const notLoaded = error instanceof PageLoadError;

  useEffect(() => setPageTitle(notLoaded ? "Not available" : "Something went wrong"), [notLoaded]);
  useEffect(() => {
    if (notLoaded && !offline) reloadOnce();
  }, [notLoaded, offline]);

  return (
    <section className="slab" style={{ padding: "var(--s5)" }} role="alert">
      <h1 className="disclose-title">
        {!notLoaded ? "Something went wrong on this page" : offline ? "This page isn't saved on this device yet" : "This page couldn't be loaded"}
      </h1>
      <p className="muted">
        {!notLoaded
          ? error instanceof Error && error.message
            ? error.message
            : "Reloading usually fixes it."
          : offline
            ? "It will open by itself when you're back online."
            : "Autumn may be unreachable right now."}
      </p>
      {notLoaded && offline ? null : (
        <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
          Reload
        </button>
      )}
    </section>
  );
}
