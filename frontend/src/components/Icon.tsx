import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";

/* Font Awesome 5 solid glyphs, the same set the server-rendered pages use
   through the CDN stylesheet, inlined as SVG so only the icons we import ship
   and nothing render-blocks on a third-party host. */
export function Icon({
  icon,
  className,
  title,
  spin,
}: {
  icon: IconDefinition;
  className?: string;
  title?: string;
  spin?: boolean;
}) {
  const [width, height, , , path] = icon.icon;
  const d = Array.isArray(path) ? path.join(" ") : path;
  const classes = ["icon", spin ? "icon--spin" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <svg
      className={classes}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      <path fill="currentColor" d={d} />
    </svg>
  );
}
