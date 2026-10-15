import type { ReactNode } from "react";

export function FieldErrors({ lines }: { lines?: string[] }) {
  if (!lines?.length) return null;
  return (
    <>
      {lines.map((line) => (
        <p key={line} className="profile-field-error" role="alert">
          {line}
        </p>
      ))}
    </>
  );
}

export function SlabHead({ title, aside }: { title: string; aside?: ReactNode }) {
  return (
    <div className="u-between u-wrap u-gap-3">
      <h2 className="disclose-title">{title}</h2>
      {aside}
    </div>
  );
}
