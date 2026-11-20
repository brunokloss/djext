// Django's CSRF token, read from its cookie (browser only). The cookie is set
// by GET /api/auth/csrf and changes on login, so read it on every request
// instead of keeping it in memory.

import { projectSlug } from "@/lib/project";

// CSRF_COOKIE_NAME in backend/config/settings.py.
export const CSRF_COOKIE = `_${projectSlug}_csrf`;

function readCookie(): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${CSRF_COOKIE}=`))
    ?.slice(CSRF_COOKIE.length + 1);
}

export async function csrfToken(): Promise<string> {
  const token = readCookie();
  if (token) return token;
  // Plain fetch, not the api client: its middleware would call us again.
  await fetch("/api/auth/csrf");
  return readCookie() ?? "";
}
