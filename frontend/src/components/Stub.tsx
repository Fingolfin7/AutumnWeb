import { AppLink, urls } from "@/app/links";

/* A page that has not been rebuilt yet. Only ever visible on the ts-react
   branch while the port is in progress. */
export function Stub({ title }: { title: string }) {
  return (
    <section className="slab" style={{ padding: "var(--s5)" }}>
      <h1 className="disclose-title">{title}</h1>
      <p className="muted">This page is being rebuilt.</p>
      <AppLink className="btn btn--ghost" href={urls.home()}>
        Go home
      </AppLink>
    </section>
  );
}
