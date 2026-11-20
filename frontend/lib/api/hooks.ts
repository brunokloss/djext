"use client";

import { createQueryHook } from "swr-openapi";
import { api } from "./client";
import type { paths } from "./schema";

// Typed SWR hooks around the API client, for Client Components. Path, params
// and response all come from schema.ts:
//
//   const { data, error, isLoading } = useApi("/api/users/me");
//   useApi("/api/users/{uuid}", { params: { path: { uuid } } });
//   useApi("/api/users/me", null); // skip until there is something to ask
//
// An error response from Django lands in `error` (its JSON body); a network
// failure is a TypeError there.
type MediaType = `${string}/${string}`;
export const useApi = createQueryHook<paths, MediaType, "api", TypeError>(
  api,
  "api",
);
