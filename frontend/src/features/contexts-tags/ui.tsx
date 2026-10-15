import type { CSSProperties, ReactNode } from "react";

/* The page heading every desk page wears (.desk-head > .page-title). */
export function DeskHead({ title }: { title: ReactNode }) {
  return (
    <div className="desk-head">
      <div>
        <h1 className="page-title">{title}</h1>
      </div>
    </div>
  );
}

/* Field errors, in the markup Django renders so focus_desk.css styles them. */
export function FieldErrors({ id, errors }: { id?: string; errors?: string[] }) {
  if (!errors?.length) return null;
  return (
    <ul className="errorlist" id={id}>
      {errors.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

/* Form-level errors (the old form.non_field_errors). */
export function FormLevelErrors({ errors }: { errors: string[] }) {
  if (!errors.length) return null;
  return (
    <ul className="errorlist nonfield" role="alert">
      {errors.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

/* A tag's colour reaches .tag-chip through the --tag custom property. */
export const tagStyle = (color: string | null | undefined) =>
  color ? ({ "--tag": color } as CSSProperties) : undefined;
