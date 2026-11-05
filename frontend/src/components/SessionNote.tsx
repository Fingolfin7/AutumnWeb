import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

/** Keep complete paragraphs/list items in previews; the full journal remains in place. */
function previewHtml(html: string) {
  const root = document.createElement("div");
  root.innerHTML = html;
  let count = 0;
  const nodes = [...root.childNodes];
  for (const node of nodes) {
    count += node.textContent?.length ?? 0;
    if (count > 350 && node !== nodes[0]) node.remove();
  }
  // A single long paragraph stays whole: never cut a sentence behind a mask.
  return root.innerHTML;
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
function timestamps(html: string) {
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
export function SessionNote({ html, text, id, identity, onEdit, search = "" }: { html?: string | null; text?: string | null; id?: string; identity?: ReactNode; onEdit?: () => void; search?: string }) {
  const generated = useId();
  const noteId = id ?? `journal-${generated}`;
  const [open, setOpen] = useState(false);
  const [stuck, setStuck] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const full = useMemo(() => {
    if (html) return html;
    const node = document.createElement("div"); node.textContent = text ?? "";
    return node.innerHTML.replace(/\n/g, "<br>");
  }, [html, text]);
  const preview = useMemo(() => {
    // A search result starts at the matching paragraph, preserving its markup.
    const node = document.createElement("div"); node.innerHTML = full;
    const needles = search.toLowerCase().match(/"[^"]+"|[^\s]+/g)?.map((word) => word.replace(/^"|"$/g, "")) ?? [];
    const matched = needles.length ? [...node.children].find((child) => needles.some((word) => child.textContent?.toLowerCase().includes(word))) : undefined;
    return previewHtml(matched && (node.textContent?.indexOf(matched.textContent ?? "") ?? 0) > 350 ? matched.outerHTML : full);
  }, [full, search]);
  const clipped = preview !== full;
  const rendered = useMemo(() => timestamps(highlight(open ? full : preview, search)), [full, preview, open, search]);
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
  return <div ref={root} className={`session-note${open ? " is-open" : ""}${clipped ? " has-overflow" : ""}`}>
    {open && stuck ? <div className="note-reading-slot"><div className="note-reading-head"><div className="note-reading-identity">{identity ?? "Session note"}</div>{actions}</div></div> : null}
    <div id={noteId} className="session-note-body" onClick={(event) => { if (!(event.target as Element).closest("a, button")) setOpen(true); }} dangerouslySetInnerHTML={{ __html: rendered }} />
    {open && !stuck ? <div className="note-reading-actions">{actions}</div> : null}
    {!open ? <button type="button" className={clipped ? "note-expand" : "note-open-short"} aria-expanded={open} aria-controls={noteId} onClick={() => setOpen(true)}>{clipped ? "Read full note" : "Open note"}</button> : null}
  </div>;
}
