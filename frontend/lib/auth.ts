import { cache } from "react";
import type { Me } from "@/lib/api/client";
import { serverApi } from "@/lib/api/server";

// For Server Components. Returns null when not logged in. Cached per request,
// so the layout and the page share one call to Django.
export const getCurrentUser = cache(async (): Promise<Me | null> => {
  const { data, response } = await (await serverApi()).GET("/api/users/me");
  if (response.status === 401) return null;
  if (!data) throw new Error(`GET /api/users/me failed: ${response.status}`);
  return data;
});

// The ways in that are on (/api/auth/providers): the password, the providers
// and the self-service pages (a page of one that is off answers 404).
export const getLoginOptions = cache(async () => {
  const { data } = await (await serverApi()).GET("/api/auth/providers");
  return data;
});
