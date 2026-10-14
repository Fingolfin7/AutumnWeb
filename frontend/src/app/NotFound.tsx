import { useEffect } from "react";
import { useLocation } from "react-router";
import { AppLink, urls } from "./links";
import { setPageTitle } from "./title";

/* Django serves the app for any path it does not own, so a path the router
   does not know either is a real 404. */
export function NotFound() {
  const { pathname } = useLocation();
  useEffect(() => {
    setPageTitle("Not found");
  }, []);
  return (
    <section className="slab" style={{ padding: "var(--s5)" }}>
      <h1 className="disclose-title">Nothing at {pathname}</h1>
      <p className="muted">This page doesn't exist, or it moved.</p>
      <AppLink className="btn btn--primary" href={urls.home()}>
        Go home
      </AppLink>
    </section>
  );
}
