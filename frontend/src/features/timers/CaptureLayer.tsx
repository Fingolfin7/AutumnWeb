import { useCallback, type ComponentProps, type MouseEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { AppLink, urls } from "@/app/links";
import { Sheet } from "@/components/Sheet";
import { CaptureForm, type CaptureMode } from "./CaptureForm";

/* In the app, capture opens over the current page: a history entry that only
   carries state, so nothing behind it remounts and Back closes the sheet. The
   real /start_timer/ URLs still work for bookmarks and new tabs. */
export function useOpenCapture() {
  const navigate = useNavigate();
  const { pathname, search, hash } = useLocation();
  return useCallback((mode: CaptureMode = "timer") => navigate(`${pathname}${search}${hash}`, { state: { capture: mode } }), [navigate, pathname, search, hash]);
}

export function CaptureLink({ mode = "timer", onClick, ...rest }: Omit<ComponentProps<typeof AppLink>, "href"> & { mode?: CaptureMode }) {
  const open = useOpenCapture();
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    open(mode);
  };
  return <AppLink {...rest} href={mode === "past" ? `${urls.startTimer()}?mode=past` : urls.startTimer()} onClick={follow} />;
}

export function CaptureLayer() {
  const navigate = useNavigate();
  const mode = (useLocation().state as { capture?: CaptureMode } | null)?.capture;
  if (!mode) return null;
  const close = () => navigate(-1);
  return <Sheet open onClose={close} title="Capture time" className="capture-sheet"><CaptureForm key={mode} mode={mode} onSaved={close} /></Sheet>;
}
