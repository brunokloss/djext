"use client";

import { useApi } from "@/lib/api/hooks";

// Fetches the logged-in user from the browser. The request goes through the
// Next proxy, so the session cookie is sent along.
export function CurrentUserClient() {
  const { data, error, isLoading } = useApi("/api/users/me");

  let email = isLoading ? "loading…" : data?.email;
  // A TypeError means the request never got an answer; anything else is
  // Django's error body (401 when the session is gone).
  if (error)
    email = error instanceof TypeError ? "unreachable" : "not logged in";

  return <p data-testid="user-client">From the browser: {email}</p>;
}
