/** One error type for every failed call, so screens can branch on cause rather
 *  than on a message string. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Section 5, tier L1. Distinguished from a server error because the two need
   *  opposite responses: an offline scan is queued and the officer carries on,
   *  a 500 is a bug and must be shown. */
  get isOffline(): boolean {
    return this.status === 0;
  }

  get isAuth(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

/** FastAPI returns `{"detail": ...}`, where `detail` is a string for our own
 *  raises and a list of objects for a validation failure. Both become one
 *  sentence, because an officer reading it is not going to parse a JSON array. */
export function messageFrom(status: number, body: unknown): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) =>
          typeof item === "object" && item !== null && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  }
  return `Request failed (HTTP ${status}).`;
}
