import { afterEach, expect, test, vi } from "vitest";
import { CSRF_COOKIE, csrfToken } from "@/lib/api/csrf";

afterEach(() => {
  // biome-ignore lint/suspicious/noDocumentCookie: test setup
  document.cookie = `${CSRF_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
  vi.unstubAllGlobals();
});

test("reads the token from the cookie", async () => {
  // biome-ignore lint/suspicious/noDocumentCookie: test setup
  document.cookie = `${CSRF_COOKIE}=abc`;
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  expect(await csrfToken()).toBe("abc");
  expect(fetch).not.toHaveBeenCalled();
});

test("asks Django for the cookie when it is missing", async () => {
  const fetch = vi.fn(async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: what the response does
    document.cookie = `${CSRF_COOKIE}=fresh`;
  });
  vi.stubGlobal("fetch", fetch);
  expect(await csrfToken()).toBe("fresh");
  expect(fetch).toHaveBeenCalledWith("/api/auth/csrf");
});
