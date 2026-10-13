/* API v2 answers failures with {"error": {code, message, details}}. Older or
   non-API endpoints may answer {"error": "..."} or {"detail": "..."}. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field errors from DRF validation, flattened to "field: message" lines. */
  fieldMessages(): string[] {
    const details = this.details;
    if (!details || typeof details !== "object") return [];
    const lines: string[] = [];
    for (const [field, value] of Object.entries(details as Record<string, unknown>)) {
      const text = Array.isArray(value) ? value.join(" ") : String(value);
      lines.push(field === "non_field_errors" ? text : `${field}: ${text}`);
    }
    return lines;
  }
}

export function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    const error = record.error;
    if (error && typeof error === "object") {
      const e = error as Record<string, unknown>;
      return new ApiError(
        status,
        String(e.code ?? "error"),
        String(e.message ?? "Something went wrong."),
        e.details,
      );
    }
    if (typeof error === "string") return new ApiError(status, "error", error);
    if (typeof record.detail === "string") return new ApiError(status, "error", record.detail);
  }
  return new ApiError(status, "http_" + status, statusText(status));
}

function statusText(status: number): string {
  if (status === 0) return "Can't reach Autumn. Check your connection.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 404) return "That no longer exists.";
  if (status === 409) return "This changed somewhere else. Reload and try again.";
  if (status >= 500) return "Autumn hit a server error. Try again in a moment.";
  return "Something went wrong.";
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const fields = error.fieldMessages();
    return fields.length ? fields.join(" ") : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
