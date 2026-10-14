import { Children, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { FocusDots } from "./FocusCard";

/* The .focus-deck: a horizontal scroll-snap carousel of cards on phones, a
   grid on the desk (CSS decides). Dots track the visible card. */
export function FocusDeck({ label, children }: { label: string; children: ReactNode }) {
  const track = useRef<HTMLDivElement>(null);
  const count = Children.toArray(children).filter(Boolean).length;
  const [active, setActive] = useState(0);

  const sync = useCallback(() => {
    const node = track.current;
    if (!node) return;
    const step = node.clientWidth + 12;
    setActive(step > 0 ? Math.round(node.scrollLeft / step) : 0);
  }, []);

  useEffect(() => {
    const node = track.current;
    if (!node) return;
    node.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    return () => {
      node.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [sync]);

  return (
    <section className="focus-deck" aria-label={label}>
      <div className="focus-track" ref={track}>
        {children}
      </div>
      <FocusDots
        count={count}
        active={Math.min(active, Math.max(0, count - 1))}
        onPick={(index) => {
          const node = track.current;
          if (node) node.scrollTo({ left: index * (node.clientWidth + 12), behavior: "smooth" });
        }}
      />
    </section>
  );
}
