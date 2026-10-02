/**
 * Where to send a user after they sign in.
 *
 * The value arrives in a query string, which means it is whatever the last
 * person to share a link decided. Used unfiltered it turns the login page into
 * an open redirect: sign in successfully and land somewhere that harvests the
 * session or simply deceives the user about where they are.
 *
 * Only same-origin, single-slash paths are allowed through. The `//` case is the
 * one that matters and is easy to overlook - a protocol-relative URL like
 * `//evil.example` starts with a slash and would pass a naive `startsWith("/")`
 * check, while the browser resolves it as a different origin entirely. Backslashes
 * are rejected for the same reason: several browsers normalise `\` to `/`, so
 * `/\evil.example` is a second spelling of the same attack.
 *
 * Anything unrecognised falls back to the dashboard rather than failing. A
 * refused redirect would be a worse answer than a slightly different landing
 * page.
 */

const FALLBACK = "/dashboard";

export function safeNextPath(raw: string | null | undefined): string {
  if (!raw) return FALLBACK;
  if (!raw.startsWith("/")) return FALLBACK;
  if (raw.startsWith("//") || raw.startsWith("/\\")) return FALLBACK;
  if (raw.includes("\\")) return FALLBACK;
  return raw;
}
