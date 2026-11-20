import { type NextRequest, NextResponse } from "next/server";
import { log } from "@/lib/log";
import {
  loggedInRedirect,
  loginRedirect,
  SESSION_COOKIE,
} from "@/lib/login-guard";
import { REQUEST_ID_HEADER, requestId } from "@/lib/request-id";

// Gives each request an id before anything else runs. It goes on to Django in
// the X-Request-Id header (the rewrites in next.config.ts and the server-side
// API calls, see lib/api/server.ts) and back to the browser in the response.
// Visits without a session cookie go to /login, and /login with a valid
// session goes on (lib/login-guard.ts).
export async function proxy(request: NextRequest) {
  const id = requestId(request.headers.get(REQUEST_ID_HEADER));
  const headers = new Headers(request.headers);
  headers.set(REQUEST_ID_HEADER, id);

  log("info", "request", `${request.method} ${request.nextUrl.pathname}`, {
    request_id: id,
  });

  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const login =
    pathname === "/login" && hasSession
      ? await loggedInRedirect(search, headers)
      : loginRedirect(pathname, search, hasSession);
  const response = login
    ? NextResponse.redirect(new URL(login, request.url))
    : NextResponse.next({ request: { headers } });
  response.headers.set(REQUEST_ID_HEADER, id);
  return response;
}

export const config = {
  // Everything but static files and
  // Sentry's tunnel, which must work logged out too (the login page).
  matcher: ["/((?!_next/static|_next/image|monitoring|favicon.ico).*)"],
};
