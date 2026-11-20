// Every request gets an id that Next and Django both log (see proxy.ts and
// backend/modules/log/middleware.py), so one search finds it on both sides.
export const REQUEST_ID_HEADER = "x-request-id";

// Same rule as Django: 8 to 64 of [A-Za-z0-9-], or a crafted header could put
// arbitrary text in the logs.
const REQUEST_ID_RE = /^[A-Za-z0-9-]{8,64}$/;

// Keeps an incoming id that looks like one; otherwise 8 hex chars.
export function requestId(incoming: string | null | undefined) {
  if (incoming && REQUEST_ID_RE.test(incoming)) return incoming;
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
