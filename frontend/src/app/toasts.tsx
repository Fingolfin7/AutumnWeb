import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  faCheckCircle,
  faExclamationCircle,
  faExclamationTriangle,
  faInfoCircle,
  faTimes,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { bootstrap } from "@/bootstrap";

export type ToastKind = "success" | "info" | "warning" | "error";
export type Celebration = "completion" | "progress";

export interface ToastInput {
  kind?: ToastKind;
  message: string;
  /** Leaves fall for a commitment met (completion) or a step forward (progress). */
  celebration?: Celebration;
  action?: { label: string; run: () => void };
  /** Milliseconds; 0 keeps it until dismissed. Errors default to 8 s. */
  duration?: number;
}

interface Toast extends ToastInput {
  id: number;
}

interface ToastApi {
  push: (toast: ToastInput) => number;
  dismiss: (id: number) => void;
  success: (message: string, extra?: Omit<ToastInput, "message" | "kind">) => number;
  error: (message: string, extra?: Omit<ToastInput, "message" | "kind">) => number;
  info: (message: string, extra?: Omit<ToastInput, "message" | "kind">) => number;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast outside ToastProvider");
  return value;
}

const ICONS = {
  success: faCheckCircle,
  info: faInfoCircle,
  warning: faExclamationTriangle,
  error: faExclamationCircle,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>(() =>
    (bootstrap().messages ?? []).map((flash, index) => ({ id: index + 1, kind: flash.kind, message: flash.text })),
  );
  const nextId = useRef(toasts.length + 1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback((input: ToastInput) => {
    const id = nextId.current++;
    setToasts((current) => [...current.slice(-3), { ...input, id }]);
    return id;
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      push,
      dismiss,
      success: (message, extra) => push({ ...extra, message, kind: "success" }),
      error: (message, extra) => push({ ...extra, message, kind: "error" }),
      info: (message, extra) => push({ ...extra, message, kind: "info" }),
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <section className="toast-region" aria-live="polite" aria-label="Notifications">
        {toasts.map((toast) => (
          <ToastView key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
        ))}
      </section>
    </ToastContext.Provider>
  );
}

function ToastView({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const kind = toast.kind ?? "success";
  const ref = useRef<HTMLDivElement>(null);
  const duration = toast.duration ?? (kind === "error" ? 8000 : toast.action ? 7000 : 4000);

  useEffect(() => {
    if (!duration) return;
    const timer = window.setTimeout(onDismiss, duration);
    return () => window.clearTimeout(timer);
  }, [duration, onDismiss]);

  useEffect(() => {
    if (toast.celebration && ref.current) playCelebration(toast.celebration, ref.current);
  }, [toast.celebration]);

  const classes = [
    "msg",
    `msg--${kind}`,
    toast.celebration ? `msg--celebration msg--celebration-${toast.celebration === "completion" ? "complete" : "progress"}` : "",
  ].join(" ");

  return (
    <div ref={ref} className={classes} role={kind === "error" || kind === "warning" ? "alert" : "status"}>
      <Icon icon={ICONS[kind]} className="msg-icon" />
      <span>{toast.message}</span>
      {toast.action ? (
        <button
          type="button"
          className="toast-action"
          onClick={() => {
            toast.action?.run();
            onDismiss();
          }}
        >
          {toast.action.label}
        </button>
      ) : null}
      <button type="button" className="toast-close" onClick={onDismiss} aria-label="Dismiss">
        <Icon icon={faTimes} />
      </button>
    </div>
  );
}

/* The leaf fall from focus_desk.js, driven by the same .celebration-* CSS. */
function playCelebration(kind: Celebration, anchor: HTMLElement) {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const src = bootstrap().static.leaf;
  if (!src) return;
  const layer = document.createElement("div");
  layer.className = "celebration-layer";
  layer.setAttribute("aria-hidden", "true");

  const makeLeaf = (single: boolean, index: number) => {
    const leaf = document.createElement("img");
    leaf.className = "celebration-leaf" + (single ? " celebration-leaf--single" : "");
    leaf.src = src;
    leaf.alt = "";
    if (!single) {
      leaf.style.setProperty("--leaf-left", `${8 + Math.random() * 84}%`);
      leaf.style.setProperty("--leaf-delay", `${index * 55}ms`);
      leaf.style.setProperty("--leaf-drift", `${Math.random() * 9 - 4.5}rem`);
      leaf.style.setProperty("--leaf-tilt", `${Math.random() * 80 - 40}deg`);
      leaf.style.setProperty("--leaf-scale", (0.72 + Math.random() * 0.45).toFixed(2));
    }
    return leaf;
  };

  if (kind === "completion") {
    for (let i = 0; i < 11; i += 1) layer.appendChild(makeLeaf(false, i));
  } else {
    const leaf = makeLeaf(true, 0);
    const rect = anchor.getBoundingClientRect();
    leaf.style.left = `${Math.round(rect.left + rect.width * 0.82)}px`;
    leaf.style.top = `${Math.round(rect.top + rect.height * 0.2)}px`;
    layer.appendChild(leaf);
  }
  document.body.appendChild(layer);
  window.setTimeout(() => layer.remove(), kind === "completion" ? 2400 : 1500);
}
