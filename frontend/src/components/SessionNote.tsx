import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { SegmentedControl } from "./ui";

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

/** One browser preference, shared by Sessions and every project journal. */
export function JournalDensityControl() {
  const density = useSyncExternalStore(subscribeDensity, readDensity);
  return <div className="journal-density"><SegmentedControl label="Journal density" value={density} options={[{ value: "full", label: "Full notes" }, { value: "preview", label: "2-line preview" }]} onChange={(value) => {
    try { localStorage.setItem(densityKey, value); } catch { /* Reading remains available when browser storage is blocked. */ }
    window.dispatchEvent(new Event(densityEvent));
  }} /></div>;
}

/** Local draft preview. Escape first; saved notes still use the server's renderer. */
export function renderNoteDraft(text: string): string {
  const node = document.createElement("div"); node.textContent = text;
  const inline = (line: string) => line
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  return node.innerHTML.split(/\n\s*\n/).map((paragraph) => {
    const lines = paragraph.split("\n");
    if (lines.every((line) => /^\d+[.)]\s/.test(line))) return `<ol>${lines.map((line) => `<li>${inline(line.replace(/^\d+[.)]\s+/, ""))}</li>`).join("")}</ol>`;
    if (lines.every((line) => /^[-*]\s/.test(line))) return `<ul>${lines.map((line) => `<li>${inline(line.slice(2))}</li>`).join("")}</ul>`;
    return `<p>${inline(paragraph).replace(/\n/g, "<br>")}</p>`;
  }).join("");
}

function highlight(html: string, query: string) {
  if (!query.trim()) return html;
  const root = document.createElement("div"); root.innerHTML = html;
  const words = query.match(/"[^"]+"|[^\s]+/g)?.map((word) => word.replace(/^"|"$/g, "")).filter(Boolean) ?? [];
  const escaped = words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!escaped.length) return html;
  const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: Text[] = []; while (walker.nextNode()) texts.push(walker.currentNode as Text);
  for (const node of texts) {
    const parts = node.data.split(pattern);
    if (parts.length < 2) continue;
    const fragment = document.createDocumentFragment();
    parts.forEach((part, index) => { const child = index % 2 ? document.createElement("mark") : document.createTextNode(part); if (index % 2) child.textContent = part; fragment.append(child); });
    node.replaceWith(fragment);
  }
  return root.innerHTML;
}

/** Mark only timestamp text, never touch the sanitized markup or saved journal. */
export function markTimestamps(html: string) {
  const root = document.createElement("div"); root.innerHTML = html;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = []; while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    if (node.parentElement?.closest("a, code, pre")) continue;
    const pattern = /(^|\n)(?:\u2014\s*)?(\d{1,2}:\d{2})\s*\u2014\s*/g;
    const matches = [...node.data.matchAll(pattern)];
    if (!matches.length) continue;
    const fragment = document.createDocumentFragment(); let offset = 0;
    for (const match of matches) {
      fragment.append(document.createTextNode(node.data.slice(offset, match.index) + (match[1] ?? "")));
      const label = document.createElement("span"); label.className = "note-timestamp"; label.textContent = match[0].slice((match[1] ?? "").length);
      fragment.append(label); offset = match.index! + match[0].length;
    }
    fragment.append(document.createTextNode(node.data.slice(offset))); node.replaceWith(fragment);
  }
  return root.innerHTML;
}

/** Sanitized API markdown or plain text. Prose opens the complete note in place. */
export function SessionNote({ html, text, id, identity, onEdit, passage, search = "" }: { html?: string | null; text?: string | null; id?: string; identity?: ReactNode; onEdit?: () => void; passage?: string; search?: string }) {
  const generated = useId();
  const noteId = id ?? `journal-${generated}`;
  const [open, setOpen] = useState(false);
  const density = useSyncExternalStore(subscribeDensity, readDensity);
  const compact = density === "preview";
  const [overflow, setOverflow] = useState(false);
  const [stuck, setStuck] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const full = useMemo(() => {
    if (html) return html;
    return renderNoteDraft(text ?? "");
  }, [html, text]);
  const preview = useMemo(() => {
    if (passage) {
      const escaped = document.createElement("div"); escaped.textContent = passage;
      return escaped.innerHTML.replace(/\n/g, "<br>");
    }
    // A search result starts at the matching paragraph, preserving its markup.
    const node = document.createElement("div"); node.innerHTML = full;
    const needles = search.toLowerCase().match(/"[^"]+"|[^\s]+/g)?.map((word) => word.replace(/^"|"$/g, "")) ?? [];
    const matched = needles.length ? [...node.children].find((child) => needles.some((word) => child.textContent?.toLowerCase().includes(word))) : undefined;
    return matched && (node.textContent?.indexOf(matched.textContent ?? "") ?? 0) > 350 ? matched.outerHTML : full;
  }, [full, search, passage]);
  const clipped = preview !== full || (compact && overflow);
  const rendered = useMemo(() => markTimestamps(highlight(open ? full : preview, search)), [full, preview, open, search]);
  useEffect(() => {
    const body = root.current?.querySelector<HTMLElement>(".session-note-body");
    if (!body || open) return;
    const measure = () => setOverflow(body.scrollHeight > body.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure); observer.observe(body);
    return () => observer.disconnect();
  }, [rendered, compact, open]);
  useEffect(() => {
    if (!open) { setStuck(false); return; }
    const heading = root.current?.closest(".journal-entry")?.querySelector(".journal-heading") ?? root.current;
    if (!heading) return;
    const top = matchMedia("(max-width: 999px)").matches ? 56 : 72;
    const observer = new IntersectionObserver(([entry]) => setStuck(!!entry && !entry.isIntersecting && entry.boundingClientRect.bottom <= top), { rootMargin: `-${top}px 0px 0px 0px` });
    observer.observe(heading);
    return () => observer.disconnect();
  }, [open]);
  const collapse = () => { setOpen(false); root.current?.closest(".journal-entry, .session-note")?.scrollIntoView({ block: "start" }); };
  if (!html && !text) return null;
  const actions = <>{onEdit ? <button className="btn btn--quiet" type="button" onClick={onEdit}>Edit</button> : null}<button className="btn btn--quiet" type="button" onClick={collapse}>Collapse</button></>;
  return <div ref={root} className={`session-note${open ? " is-open" : ""}${compact ? " is-compact" : ""}${clipped ? " has-overflow" : ""}`}>
    {open && stuck ? <div className="note-reading-slot"><div className="note-reading-head"><div className="note-reading-identity">{identity ?? "Session note"}</div>{actions}</div></div> : null}
    <div id={noteId} className="session-note-body" onClick={(event) => { if (!(event.target as Element).closest("a, button")) setOpen(true); }} dangerouslySetInnerHTML={{ __html: rendered }} />
    {open && !stuck ? <div className="note-reading-actions">{actions}</div> : null}
    {!open ? <button type="button" className={`${clipped ? "note-expand" : "note-open-short"} quiet-link`} aria-expanded={open} aria-controls={noteId} onClick={() => setOpen(true)}>{clipped ? "Read full note" : "Open note"}</button> : null}
  </div>;
}
