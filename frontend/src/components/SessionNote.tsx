import { useState } from "react";

/* A session note. The server renders markdown and sanitises it with nh3
   (include=note_html), so the HTML here is trusted output of that one
   sanitiser; plain notes fall back to text. Long notes clamp and expand on
   click, as on the server-rendered pages; links inside still work. */
export function SessionNote({ html, text, id }: { html?: string | null; text?: string | null; id?: string }) {
  const [open, setOpen] = useState(false);
  if (!html && !text) return null;
  const toggle = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest("a")) return;
    setOpen((value) => !value);
  };
  const className = `session-note${open ? " is-open" : ""}`;
  if (html) {
    return <div id={id} className={className} onClick={toggle} dangerouslySetInnerHTML={{ __html: html }} />;
  }
  return (
    <div id={id} className={className} onClick={toggle} style={{ whiteSpace: "pre-wrap" }}>
      {text}
    </div>
  );
}
