import { backendUrl } from "@/lib/api/backend-url";
import { nextPath } from "@/lib/next-path";
import { projectSlug } from "@/lib/project";

// SESSION_COOKIE_NAME in backend/config/settings.py.
export const SESSION_COOKIE = `_${projectSlug}_session`;

// Where an anonymous visit to `pathname` must go, or null to let it through.
//
// Only an optimistic check: it looks at whether the session cookie exists, not
// whether it is still valid (that would cost a call to Django on every
// request). The pages still check the session with Django; this only turns
// the obvious case into a real 307. Without it, a production build sends the
// page's static shell first and can only redirect in the browser.
export function loginRedirect(
  pathname: string,
  search: string,
  hasSession: boolean,
): string | null {
  if (hasSession) return null;
  if (pathname === "/login") return null;
  // Django's own URLs (behind the proxy) do their own login checks.
  if (pathname === "/api" || pathname.startsWith("/api/")) return null;
  // Files from public/ (robots.txt, images…) and Next's internals.
  if (
    pathname.startsWith("/_next/") ||
    pathname.split("/").pop()?.includes(".")
  )
    return null;
  if (pathname === "/") return "/login";
  return `/login?next=${encodeURIComponent(pathname + search)}`;
}

// Where a visit to /login with a session cookie must go when that session is
// still valid (its ?next=, or /), or null to show the login page. Unlike
// loginRedirect it asks Django (/api/users/me, cached there), since a stale
// cookie sent to / would come straight back here, forever. Only /login with a
// cookie pays for that call. Django down or slow: the page shows, and checks
// again itself.
export async function loggedInRedirect(
  search: string,
  headers: Headers,
): Promise<string | null> {
  try {
    const response = await fetch(`${backendUrl}/api/users/me`, {
      headers,
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
  } catch {
    return null;
  }
  return nextPath(new URLSearchParams(search).get("next") ?? undefined) ?? "/";
}
