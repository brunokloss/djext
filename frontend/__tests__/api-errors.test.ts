import { afterEach, expect, test, vi } from "vitest";

const captureException = vi.hoisted(() => vi.fn());
vi.mock("@sentry/nextjs", () => ({ captureException }));

import { ApiError, api } from "@/lib/api/client";

// Node's Request needs an absolute URL; the browser resolves the relative one.
const baseUrl = "http://localhost:3000";

afterEach(() => captureException.mockClear());

function answer(status: number) {
  return async () =>
    new Response("{}", { status, headers: { "x-request-id": "req12345" } });
}

test("a 5xx from Django goes to Sentry with the request id", async () => {
  await api.GET("/api/users/me", { baseUrl, fetch: answer(500) });
  expect(captureException).toHaveBeenCalledOnce();
  const [error, hint] = captureException.mock.calls[0];
  expect(error).toBeInstanceOf(ApiError);
  expect(error.message).toBe("GET /api/users/me answered 500");
  expect(hint.tags).toEqual({ request_id: "req12345" });
});

test("4xx answers are not errors to report", async () => {
  await api.GET("/api/users/me", { baseUrl, fetch: answer(401) });
  expect(captureException).not.toHaveBeenCalled();
});
