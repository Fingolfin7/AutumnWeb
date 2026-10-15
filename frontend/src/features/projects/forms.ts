import { ApiError } from "@/api/errors";

export interface SplitErrors {
  /** Messages keyed by the form field they belong to. */
  fields: Record<string, string>;
  /** Everything else: shown once above the form. */
  general: string[];
}

/* Spreads an API failure over a form: DRF validation errors land under their
   own field, a 409 conflict ("name already exists") lands under `conflictField`
   when the form has one, and anything else becomes a general message. */
export function splitErrors(error: unknown, known: string[], conflictField?: string): SplitErrors {
  const result: SplitErrors = { fields: {}, general: [] };
  if (!error) return result;
  if (!(error instanceof ApiError)) {
    result.general.push(error instanceof Error ? error.message : "Something went wrong.");
    return result;
  }
  /* Its details are the current record, not field errors. */
  if (conflictCurrent(error)) {
    result.general.push(error.message);
    return result;
  }
  const details = error.details;
  if (details && typeof details === "object") {
    for (const [field, value] of Object.entries(details as Record<string, unknown>)) {
      const text = Array.isArray(value) ? value.join(" ") : String(value);
      if (known.includes(field)) result.fields[field] = text;
      else result.general.push(field === "non_field_errors" ? text : `${field}: ${text}`);
    }
    if (result.general.length || Object.keys(result.fields).length) return result;
  }
  if (error.status === 409 && conflictField && error.code === "conflict" && /already exists/i.test(error.message)) {
    result.fields[conflictField] = error.message;
  } else {
    result.general.push(error.message);
  }
  return result;
}

/* A 409 version_conflict (If-Match no longer matches) carries the record as it
   is now in error.details.current. Null for any other failure. */
export function conflictCurrent<T extends { version?: number }>(error: unknown): T | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "version_conflict") return null;
  const details = error.details;
  if (!details || typeof details !== "object" || !("current" in details)) return null;
  const current = details.current;
  return current && typeof current === "object" ? (current as T) : null;
}
