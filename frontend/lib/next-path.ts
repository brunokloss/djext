// The ?next= path to go to after login (Django's login_required sends it).
// Only same-origin paths: "//evil.com", "/\evil.com" or "https://..." would be
// an open redirect. Browsers read "\" as "/" and drop tabs and newlines, so
// reject those outright and check the origin the way a browser resolves it.
const ORIGIN = "http://next-path.invalid";

function hasUnsafeChar(value: string) {
  for (const char of value) {
    const code = char.charCodeAt(0);
    if (char === "\\" || code < 0x20 || code === 0x7f) return true;
  }
  return false;
}

export function nextPath(value: string | string[] | undefined) {
  if (typeof value !== "string") return undefined;
  if (!value.startsWith("/") || hasUnsafeChar(value)) return undefined;
  if (!URL.canParse(value, ORIGIN)) return undefined;
  const url = new URL(value, ORIGIN);
  if (url.origin !== ORIGIN) return undefined;
  return url.pathname + url.search + url.hash;
}
