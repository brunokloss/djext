import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { afterEach, expect, test, vi } from "vitest";
import { CurrentUserClient } from "@/components/current-user-client";
import { api } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({ api: { GET: vi.fn() } }));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

// A fresh SWR cache per test, so one test's answer doesn't leak into the next.
function renderFresh(ui: ReactNode) {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      {ui}
    </SWRConfig>,
  );
}

test("shows the logged-in user's email", async () => {
  vi.mocked(api.GET).mockResolvedValue({
    data: { email: "ana@example.com" },
    error: undefined,
    response: new Response(),
  } as never);
  renderFresh(<CurrentUserClient />);
  expect(
    await screen.findByText("From the browser: ana@example.com"),
  ).toBeDefined();
  expect(api.GET).toHaveBeenCalledWith("/api/users/me", undefined);
});

test("shows not logged in when the API answers with an error", async () => {
  vi.mocked(api.GET).mockResolvedValue({
    data: undefined,
    error: { detail: "Unauthorized" },
    response: new Response(null, { status: 401 }),
  } as never);
  renderFresh(<CurrentUserClient />);
  expect(
    await screen.findByText("From the browser: not logged in"),
  ).toBeDefined();
});

test("shows unreachable when the request fails", async () => {
  vi.mocked(api.GET).mockRejectedValue(new TypeError("Failed to fetch"));
  renderFresh(<CurrentUserClient />);
  expect(
    await screen.findByText("From the browser: unreachable"),
  ).toBeDefined();
});
