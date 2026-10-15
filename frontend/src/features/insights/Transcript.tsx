import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { faCheck, faCopy } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import type { Run } from "./run";
import type { Turn } from "./logic";

/* One row of the conversation, whether it came from the server or is the
   exchange being streamed right now. */
export interface Item extends Turn {
  key: string;
  /** Plain text shown instead of `html` (an answer still arriving). */
  plain: string | null;
  streaming: boolean;
  stopped: boolean;
}

export function savedItems(turns: Turn[]): Item[] {
  return turns.map((turn, index) => ({ ...turn, key: `saved-${index}`, plain: null, streaming: false, stopped: false }));
}

/* The run's question and (partial) answer, drawn after the saved messages. */
export function runItems(run: Run): Item[] {
  const answered = run.status === "done" && !!run.html;
  return [
    { key: `run-${run.id}-q`, role: "user", content: run.prompt, html: "", plain: run.prompt, model: "", sources: [], error: false, streaming: false, stopped: false },
    {
      key: `run-${run.id}-a`,
      role: "assistant",
      content: run.text,
      html: answered ? (run.html ?? "") : "",
      plain: answered ? null : run.text,
      model: run.model,
      sources: run.sources,
      error: run.status === "error",
      streaming: run.status === "streaming",
      stopped: run.status === "stopped",
    },
  ];
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      className="copy-btn"
      title="Copy message"
      aria-label="Copy message"
      onClick={(event) => {
        event.stopPropagation();
        void navigator.clipboard?.writeText(text).then(() => setCopied(true));
      }}
    >
      <Icon icon={copied ? faCheck : faCopy} />
    </button>
  );
}

function Message({ item, selecting, selected, onToggle }: { item: Item; selecting: boolean; selected: boolean; onToggle: () => void }) {
  const className = [
    item.role === "user" ? "user-message" : "assistant-message",
    item.streaming ? "streaming" : "",
    item.error ? "stream-error" : "",
    selected ? "msg-selected" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const interactive = selecting
    ? {
        onClick: (event: React.MouseEvent) => {
          event.preventDefault();
          onToggle();
        },
        onKeyDown: (event: KeyboardEvent) => {
          if (event.key === " " || event.key === "Enter") {
            event.preventDefault();
            onToggle();
          }
        },
        tabIndex: 0,
        role: "checkbox" as const,
        "aria-checked": selected,
      }
    : {};
  let body: ReactNode;
  if (item.plain !== null) {
    body = (
      <div className="message-content" style={{ whiteSpace: "pre-wrap" }}>
        {item.plain}
      </div>
    );
  } else {
    /* Server-rendered markdown, sanitised on the server (core markdown_render),
       the same HTML the old page printed with |markdown|safe. */
    body = <div className="message-content" dangerouslySetInnerHTML={{ __html: item.html }} />;
  }
  return (
    <div className={className} data-model={item.role === "assistant" ? item.model : undefined} {...interactive}>
      <CopyButton text={item.content} />
      {body}
      {item.stopped ? <small className="muted"> Stopped.</small> : null}
      {item.sources.length ? (
        <small className="assistant-sources">
          <strong>Sources:</strong>{" "}
          {item.sources.map((source, index) => (
            <span key={`${source.link}-${index}`}>
              <a href={source.link} className="plain-link" target="_blank" rel="noopener noreferrer">
                {source.title || String(index + 1)}
              </a>
              {index < item.sources.length - 1 ? ", " : null}
            </span>
          ))}
        </small>
      ) : null}
    </div>
  );
}

export function Transcript({
  items,
  selecting,
  selected,
  onToggle,
  empty,
}: {
  items: Item[];
  selecting: boolean;
  selected: ReadonlySet<string>;
  onToggle: (key: string) => void;
  empty: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const last = items[items.length - 1];
  const signature = `${items.length}:${last?.plain?.length ?? last?.html.length ?? 0}:${last?.streaming}`;

  /* Follow the answer as it grows, unless you scrolled up to read. */
  useLayoutEffect(() => {
    const node = ref.current;
    /* Sending a question always brings you to the bottom. */
    if (last?.streaming && !last.plain) stick.current = true;
    if (node && stick.current) node.scrollTop = node.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  return (
    <div
      id="conversation-container"
      ref={ref}
      className={`conversation-container${selecting ? " selecting" : ""}`}
      onScroll={(event) => {
        const node = event.currentTarget;
        stick.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
      }}
    >
      {items.length ? (
        items.map((item) => <Message key={item.key} item={item} selecting={selecting} selected={selected.has(item.key)} onToggle={() => onToggle(item.key)} />)
      ) : (
        empty
      )}
    </div>
  );
}
