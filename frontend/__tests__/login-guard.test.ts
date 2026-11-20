import { afterEach, expect, test, vi } from "vitest";
import {
  loggedInRedirect,
  loginRedirect,
  SESSION_COOKIE,
} from "@/lib/login-guard";

afterEach(() => vi.unstubAllGlobals());

function django(answer: Response | Error) {
  const fetch = vi.fn(() =>
    answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

test("anonymous visits to pages go to /login", () => {
  expect(loginRedirect("/", "", false)).toBe("/login");
  expect(loginRedirect("/reports", "?page=2", false)).toBe(
    "/login?next=%2Freports%3Fpage%3D2",
  );
});

test("a session cookie lets the request through", () => {
  expect(loginRedirect("/", "", true)).toBeNull();
  expect(loginRedirect("/reports", "", true)).toBeNull();
});

test("the logged-out pages, Django and files are left alone", () => {
  for (const path of [
    "/login",
    "/signup",
    "/verify",
    "/forgot-password",
    "/reset-password",
    "/api",
    "/api/docs",
    "/_next/data/x.json",
    "/robots.txt",
  ]) {
    expect(loginRedirect(path, "", false)).toBeNull();
  }
});

test("a valid session on /login goes to ?next= or /", async () => {
  const fetch = django(new Response("{}", { status: 200 }));
  const headers = new Headers({ cookie: `${SESSION_COOKIE}=abc` });
  expect(await loggedInRedirect("", headers)).toBe("/");
  expect(await loggedInRedirect("?next=%2Fapi%2Fdocs", headers)).toBe(
    "/api/docs",
  );
  // Never off-site.
  expect(await loggedInRedirect("?next=//evil.com", headers)).toBe("/");
  expect(fetch).toHaveBeenCalledWith(
    expect.stringMatching(/\/api\/users\/me$/),
    expect.objectContaining({ headers }),
  );
});

test("a stale cookie or Django down shows the login page", async () => {
  django(new Response("{}", { status: 401 }));
  expect(await loggedInRedirect("", new Headers())).toBeNull();
  django(new Error("ECONNREFUSED"));
  expect(await loggedInRedirect("", new Headers())).toBeNull();
});
