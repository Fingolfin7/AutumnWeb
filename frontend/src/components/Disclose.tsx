import { useState, type ReactNode } from "react";
import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "./Icon";

/* A collapsible .slab (focus_desk.css .disclose). The open/closed choice is
   remembered per slab so a section you fold away stays folded. */
export function Disclose({
  id,
  icon,
  iconClass,
  title,
  summary,
  className,
  children,
  defaultOpen = true,
  slab = true,
  headClassName,
}: {
  id: string;
  icon: IconDefinition;
  iconClass?: string;
  title: ReactNode;
  summary?: ReactNode;
  className?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  /** false renders a nested disclosure without the .slab surface. */
  slab?: boolean;
  headClassName?: string;
}) {
  const key = `autumn:disclose:${id}`;
  const [open, setOpen] = useState(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? defaultOpen : stored === "1";
    } catch {
      return defaultOpen;
    }
  });

  const toggle = () => {
    setOpen((value) => {
      try {
        window.localStorage.setItem(key, value ? "0" : "1");
      } catch {
        /* storage unavailable: still toggles for this visit */
      }
      return !value;
    });
  };

  return (
    <section className={`${slab ? "slab " : ""}disclose${open ? "" : " is-closed"}${className ? " " + className : ""}`}>
      <button className={`disclose-head${headClassName ? " " + headClassName : ""}`} type="button" aria-expanded={open} onClick={toggle}>
        <Icon icon={icon} className={`disclose-icon${iconClass ? " " + iconClass : ""}`} />
        <span className="disclose-title">{title}</span>
        {summary !== undefined ? <span className="disclose-summary">{summary}</span> : null}
        <Icon icon={faChevronDown} className="disclose-chevron" />
      </button>
      {open ? <div className="disclose-body">{children}</div> : null}
    </section>
  );
}
