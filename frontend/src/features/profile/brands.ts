import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";
import githubSvg from "@fortawesome/fontawesome-free/svgs/brands/github.svg?raw";
import googleSvg from "@fortawesome/fontawesome-free/svgs/brands/google.svg?raw";

/* The brand marks the old page drew with `fab fa-google` / `fab fa-github`.
   The app only bundles the solid icon set, so read these two glyphs out of
   the Font Awesome package the server-rendered pages already depend on. */
function fromSvg(svg: string, name: string): IconDefinition {
  const width = /viewBox="0 0 (\d+) (\d+)"/.exec(svg);
  const path = /<path d="([^"]+)"/.exec(svg);
  return {
    prefix: "fab" as unknown as IconDefinition["prefix"],
    iconName: name as unknown as IconDefinition["iconName"],
    icon: [Number(width?.[1] ?? 512), Number(width?.[2] ?? 512), [], "", path?.[1] ?? ""],
  };
}

export const brandIcons: Record<string, IconDefinition> = {
  github: fromSvg(githubSvg, "github"),
  google: fromSvg(googleSvg, "google"),
};
