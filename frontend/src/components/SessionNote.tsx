import { useLayoutEffect, useRef, useState } from "react";

/** Sanitized API markdown or plain text. Expand only when the note overflows. */
export function SessionNote({ html, text, id }: { html?: string | null; text?: string | null; id?: string }) {
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
    <div className={`session-note${open ? " is-open" : ""}`}>
      {html ? <div ref={body} id={id} className="session-note-body" dangerouslySetInnerHTML={{ __html: html }} /> : <div ref={body} id={id} className="session-note-body session-note-body--plain">{text}</div>}
      {overflows ? <button type="button" className="note-expand" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}>{open ? "Show less" : "Read more"}</button> : null}
    </div>
  );
}
