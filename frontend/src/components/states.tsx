import type { ReactNode } from "react";
import { faExclamationCircle, faRedo } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "./Icon";
import { errorMessage } from "@/api/errors";
import { useOnline } from "@/lib/useOnline";

export function Skeleton({ lines = 3, height = "1.1rem" }: { lines?: number; height?: string }) {
  /* Offline, a query with nothing saved waits (paused) instead of failing:
     say so rather than shimmer forever. It loads by itself once back. */
  const online = useOnline();
  if (!online) {
    return (
      <p className="empty" role="status">
        You're offline, and this hasn't been saved on this device yet. It will load when you're back online.
      </p>
    );
  }
  return (
    <div className="skeleton-stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className="skeleton" style={{ height, width: `${92 - index * 11}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="msg msg--error" role="alert">
      <Icon icon={faExclamationCircle} className="msg-icon" />
      <span>{errorMessage(error)}</span>
      {onRetry ? (
        <button type="button" className="toast-action" onClick={onRetry}>
          <Icon icon={faRedo} /> Retry
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
