import { ApiError, errorMessage } from "@/api/errors";

/* Server failures sorted into "belongs to this field" and "belongs to the
   form". API v2 answers validation failures as
   {"error": {"code": "validation_error", "details": {field: [messages]}}} and
   name clashes as a 409 {"error": {"code": "conflict", "message": ...}}. */
export interface FormErrors {
  fields: Record<string, string[]>;
  general: string[];
}

export const NO_ERRORS: FormErrors = { fields: {}, general: [] };

export interface ParseOptions {
  /** API field name -> form field name, for fields the form names differently. */
  fieldMap?: Record<string, string>;
  /** Where a 409 conflict message belongs (the name field, for contexts/tags). */
  conflictField?: string;
}

function toLines(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(toLines);
  if (value && typeof value === "object") return Object.values(value).flatMap(toLines);
  return value === undefined || value === null ? [] : [String(value)];
}

export function parseFormErrors(error: unknown, options: ParseOptions = {}): FormErrors {
  const result: FormErrors = { fields: {}, general: [] };
  const add = (field: string | null, lines: string[]) => {
    if (!lines.length) return;
    if (field === null) result.general.push(...lines);
    else (result.fields[field] ??= []).push(...lines);
  };

  if (!(error instanceof ApiError)) {
    add(null, [errorMessage(error)]);
    return result;
  }

  const details = error.details;
  if (error.status === 400 && details && typeof details === "object" && !Array.isArray(details)) {
    for (const [key, value] of Object.entries(details as Record<string, unknown>)) {
      if (key === "non_field_errors") add(null, toLines(value));
      else add(options.fieldMap?.[key] ?? key, toLines(value));
    }
    if (!result.general.length && !Object.keys(result.fields).length) add(null, [error.message]);
    return result;
  }
  if (error.status === 409 && options.conflictField) {
    add(options.conflictField, [error.message]);
    return result;
  }
  add(null, [error.message]);
  return result;
}

export function hasErrors(errors: FormErrors): boolean {
  return errors.general.length > 0 || Object.keys(errors.fields).length > 0;
}
