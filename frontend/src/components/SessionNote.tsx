import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Sanitized API markdown or plain text. Expand only when the note overflows. */
export function SessionNote({ html, text, id, identity, onEdit }: { html?: string | null; text?: string | null; id?: string; identity?: ReactNode; onEdit?: () => void }) {
  const generated = useId();
  const noteId = id ?? `journal-${generated}`;
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = body.current;
    if (!node || open) return;
    const measure = () => setOverflows(node.scrollHeight > node.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [html, text, open]);
  if (!html && !text) return null;
  return (
    <div className={`session-note${open ? " is-open" : ""}${overflows ? " has-overflow" : ""}`}>
      {open ? <div className="note-reading-head">
        <div className="note-reading-identity">{identity ?? "Session note"}</div>
        <button className="btn btn--quiet" type="button" onClick={() => { setOpen(false); body.current?.closest(".journal-entry, .session-note")?.scrollIntoView({ block: "start" }); }}>Collapse</button>
        {onEdit ? <button className="btn btn--quiet" type="button" onClick={onEdit}>Edit</button> : null}
      </div> : null}
      {html ? <div ref={body} id={noteId} className="session-note-body" dangerouslySetInnerHTML={{ __html: html }} /> : <div ref={body} id={noteId} className="session-note-body session-note-body--plain">{text}</div>}
      {onEdit ? <button className="note-tap-edit" type="button" onClick={onEdit} aria-label="Edit this note in place">Edit note</button> : null}
      {overflows ? <button type="button" className="note-expand" aria-expanded={open} aria-controls={noteId} onClick={() => { if (open) body.current?.closest(".journal-entry, .session-note")?.scrollIntoView({ block: "start" }); setOpen((value) => !value); }}>{open ? "Show less" : "Read more"}</button> : null}
    </div>
  );
}
