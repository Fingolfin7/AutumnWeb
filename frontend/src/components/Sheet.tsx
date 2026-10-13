import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/* Focus handling shared by the bottom sheet and centred dialogs: focus the
   first control on open, trap Tab inside, close on Escape, and hand focus
   back to whatever opened it. */
function useModalFocus(open: boolean, onClose: () => void, panel: React.RefObject<HTMLElement | null>) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const node = panel.current;
    const focusables = () =>
      Array.from(
        node?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    const preferred = node?.querySelector<HTMLElement>("[data-autofocus]");
    (preferred ?? focusables()[0] ?? node)?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const first = items[0]!;
      const last = items[items.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      opener?.focus?.();
    };
  }, [open, panel]);
}

/** The phone-style bottom sheet (.sheet in focus_desk.css). */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useModalFocus(open, onClose, panel);
  return createPortal(
    <div className={`sheet${open ? " is-open" : ""}`} role="dialog" aria-modal="true" aria-label={title} aria-hidden={!open}>
      <div className="sheet-scrim" onClick={onClose} />
      <div className="sheet-panel" ref={panel} tabIndex={-1}>
        <div className="sheet-grab" />
        {title ? <p className="sheet-title">{title}</p> : null}
        {children}
      </div>
    </div>,
    document.body,
  );
}

/** A centred dialog for confirmations and short forms. Unmounted when closed. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useModalFocus(open, onClose, panel);
  if (!open) return null;
  return createPortal(
    <>
      <div className="dialog-scrim" onClick={onClose} />
      <div
        className="dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panel}
        tabIndex={-1}
        style={wide ? { width: "min(46rem, calc(100vw - 1.5rem))" } : undefined}
      >
        <h2 className="dialog-title" id={titleId}>
          {title}
        </h2>
        {children}
      </div>
    </>,
    document.body,
  );
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  danger,
  busy,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title}>
      <div className="muted">{body}</div>
      <div className="dialog-actions">
        <button type="button" className="btn btn--ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className={`btn ${danger ? "btn--danger" : "btn--primary"}`}
          onClick={onConfirm}
          disabled={busy}
          data-autofocus
        >
          {confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
