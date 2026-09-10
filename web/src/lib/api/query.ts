/**
 * Query-string building. **Deliberately not a client module and not a server
 * module — both sides need it.**
 *
 * This lived in `client.ts` next to `apiFetch`, which is `"use client"`. That
 * made `withQuery` a client export, and a Server Component importing it got a
 * reference to a client function it is not allowed to invoke:
 *
 *     Attempted to call withQuery() from the server but withQuery is on the
 *     client. It's not possible to invoke a client function from the server.
 *
 * Every Server Component on the dashboard calls `serverFetch`, and `serverFetch`
 * calls this — so every dashboard view failed, and `tryServerFetch` turned the
 * failure into the same polite "could not be loaded" panel that an expired
 * session produces. It survived review because nothing had rendered against a
 * populated API until `api/demo.py` gave it 260 scans to draw.
 *
 * The rule this file exists to enforce: a helper used on both sides of the
 * server/client boundary belongs in a module that declares neither.
 */
export type Query = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    // An empty string is dropped alongside null and undefined on purpose: the
    // filter bar renders "All districts" as `""`, and `?district=` would be
    // sent to the API as a real filter matching nothing.
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}
