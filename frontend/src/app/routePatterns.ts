import type { ComponentType } from "react";

/* Every page the React router serves. Add an entry when a page moves into
   the app AND delete its Django route, so the server's catch-all hands the
   URL to the app (AutumnWeb/urls.py). Loaders are dynamic imports, so this
   table can be imported anywhere (links check it) without pulling pages in. */
export interface PageEntry {
  path: string;
  load: () => Promise<{ default: ComponentType }>;
  /** Browser tab title; pages may refine it with useTitle. */
  title: string;
}

export const pages: PageEntry[] = [];

export const appRoutePatterns: string[] = pages.map((page) => page.path);
