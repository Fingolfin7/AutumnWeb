/* The browser tab title: the page's own title, prefixed with the running
   timer while one is going, so a glance at the tab bar shows the clock. */
let pageTitle = "Autumn";
let live: string | null = null;

function apply() {
  const base = pageTitle === "Autumn" ? "Autumn" : `${pageTitle} · Autumn`;
  document.title = live ? `${live} · ${base}` : base;
}

export function setPageTitle(title: string) {
  pageTitle = title;
  apply();
}

export function setLiveTitle(text: string | null) {
  if (text === live) return;
  live = text;
  apply();
}
