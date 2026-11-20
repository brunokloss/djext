import { afterEach, expect, test, vi } from "vitest";

vi.mock("next/headers", () => ({
  headers: async () =>
    new Headers({
      "x-request-id": "abcd1234",
      "x-forwarded-for": "203.0.113.7",
    }),
  cookies: async () => ({ toString: () => "session=s" }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

test("sends the browser's cookies, request id and IP to Django", async () => {
  const fetch = vi.fn(async () => Response.json({ status: "ok" }));
  vi.stubGlobal("fetch", fetch);
  const { serverApi } = await import("@/lib/api/server");

  await (await serverApi()).GET("/api/health");

  const request = (fetch.mock.calls[0] as unknown as [Request])[0];
  expect(request.headers.get("cookie")).toBe("session=s");
  expect(request.headers.get("x-request-id")).toBe("abcd1234");
  expect(request.headers.get("x-forwarded-for")).toBe("203.0.113.7");
});
