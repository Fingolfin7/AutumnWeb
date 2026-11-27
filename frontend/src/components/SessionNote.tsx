import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { SegmentedControl } from "./ui";

/* Full notes or a 2-line preview: one choice per device, shared by every
   journal on the page and kept across visits. */
const densityKey = "autumn:journal-density";
const densityEvent = "autumn:journal-density";
function readDensity(): "full" | "preview" {
  try { return localStorage.getItem(densityKey) === "preview" ? "preview" : "full"; } catch { return "full"; }
}
function subscribeDensity(update: () => void) {
  window.addEventListener("storage", update);
  window.addEventListener(densityEvent, update);
  return () => { window.removeEventListener("storage", update); window.removeEventListener(densityEvent, update); };
}

export function JournalDensityControl() {
  const density = useSyncExternalStore(subscribeDensity, readDensity);
  return <div className="journal-density"><SegmentedControl label="Journal density" value={density} options={[{ value: "full", label: "Full notes" }, { value: "preview", label: "2-line preview" }]} onChange={(value) => {
    try { localStorage.setItem(densityKey, value); } catch { /* Reading still works when storage is blocked. */ }
    window.dispatchEvent(new Event(densityEvent));
  }} /></div>;
}

/** The words of a search, keeping "quoted phrases" whole. */
export function searchWords(search: string | undefined): string[] {
  return search?.toLowerCase().match(/"[^"]+"|[^\s]+/g)?.map((word) => word.replace(/^"|"$/g, "")).filter(Boolean) ?? [];
}

/* Text-node passes over the sanitized HTML: they never touch markup, only
   wrap matched text, so links and formatting survive. */
function eachText(root: HTMLElement, visit: (node: Text) => void) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  nodes.forEach(visit);
}

function highlight(root: HTMLElement, words: string[]) {
  if (!words.length) return;
  const pattern = new RegExp(`(${words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  eachText(root, (node) => {
    const parts = node.data.split(pattern);
    if (parts.length < 2) return;
    node.replaceWith(...parts.map((part, index) => {
      if (index % 2 === 0) return document.createTextNode(part);
      const mark = document.createElement("mark");
      mark.textContent = part;
      return mark;
    }));
  });
}

/* "— 09:45 — " stamps (the timer's Insert timestamp) become quiet labels. */
function markTimestamps(root: HTMLElement) {
  const pattern = /(^|\n)(?:—\s*)?(\d{1,2}:\d{2})\s*—\s*/g;
  eachText(root, (node) => {
    if (node.parentElement?.closest("a, code, pre")) return;
    const matches = [...node.data.matchAll(pattern)];
    if (!matches.length) return;
    const parts: Node[] = [];
    let offset = 0;
    for (const match of matches) {
      const lead = match[1] ?? "";
      parts.push(document.createTextNode(node.data.slice(offset, match.index) + lead));
      const label = document.createElement("span");
      label.className = "note-timestamp";
      label.textContent = `${match[2]} –`;
      parts.push(label, document.createTextNode(" "));
      offset = match.index! + match[0].length;
    }
    parts.push(document.createTextNode(node.data.slice(offset)));
    node.replaceWith(...parts);
  });
}

function plainHtml(text: string) {
  const node = document.createElement("div");
  node.textContent = text;
  return node.innerHTML.split(/\n\s*\n/).map((paragraph) => `<p>${paragraph.replace(/\n/g, "<br>")}</p>`).join("");
}

/* A session note as the journal reads it. The server renders markdown and
   sanitises it with nh3 (include=note_html), so the HTML here is trusted
   output of that one sanitiser; plain notes fall back to escaped text. With a
   search, the note opens at the matching paragraph (or the passage a related
   match was found by) and marks the words; "Read full note" shows the rest.
   `clamp` opens it as a preview whatever the device's journal density. */
export function SessionNote({ html, text, id, passage, search, clamp }: { html?: string | null; text?: string | null; id?: string; passage?: string | null; search?: string; clamp?: boolean }) {
  const generated = useId();
  const noteId = id ?? `note-${generated}`;
  const [open, setOpen] = useState(false);
  const compact = useSyncExternalStore(subscribeDensity, readDensity) === "preview" || !!clamp;
  const [overflow, setOverflow] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const words = useMemo(() => searchWords(search), [search]);
  const full = useMemo(() => html || plainHtml(text ?? ""), [html, text]);
  const excerpt = useMemo(() => {
    if (passage) return plainHtml(passage);
    if (!words.length) return full;
    const node = document.createElement("div");
    node.innerHTML = full;
    const hit = [...node.children].find((child) => words.some((word) => child.textContent?.toLowerCase().includes(word)));
    return hit && hit !== node.firstElementChild ? hit.outerHTML : full;
  }, [full, passage, words]);
  const rendered = useMemo(() => {
    const node = document.createElement("div");
    node.innerHTML = open ? full : excerpt;
    highlight(node, words);
    markTimestamps(node);
    return node.innerHTML;
  }, [open, full, excerpt, words]);
  useEffect(() => {
    const node = body.current;
    if (!node || open || !compact) { setOverflow(false); return; }
    const measure = () => setOverflow(node.scrollHeight > node.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [rendered, compact, open]);
  if (!html && !text) return null;
  const clipped = excerpt !== full || overflow;
  const toggle = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest("a, button")) return;
    if (open || clipped) setOpen(!open);
  };
  return (
    <div className={`session-note${open ? " is-open" : ""}${compact ? " is-compact" : ""}`}>
      <div id={noteId} ref={body} className="session-note-body" onClick={toggle} dangerouslySetInnerHTML={{ __html: rendered }} />
      {clipped && !open ? <button type="button" className="note-expand quiet-link" aria-expanded={false} aria-controls={noteId} onClick={() => setOpen(true)}>Read full note</button> : null}
      {open && (clipped || compact) ? <button type="button" className="note-expand quiet-link" aria-expanded aria-controls={noteId} onClick={() => setOpen(false)}>Collapse</button> : null}
    </div>
  );
}
