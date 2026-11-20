import { cookies, headers } from "next/headers";
import createClient from "openapi-fetch";
import { REQUEST_ID_HEADER } from "@/lib/request-id";
import { backendUrl } from "./backend-url";
import type { paths } from "./schema";

// The API client for Server Components, which call Django directly:
// `(await serverApi()).GET(...)`. Every call carries the browser's cookies
// (or Django sees an anonymous request), the page's request id from
// proxy.ts (so Django logs it under that id) and the browser's
// X-Forwarded-For, which Next fills in like for the rewrites (without it
// Django sees this server's IP, in the logs and in the rate limits). Reading
// them first also marks the page as rendered per request.
export async function serverApi() {
  const incoming = await headers();
  const id = incoming.get(REQUEST_ID_HEADER);
  const forwardedFor = incoming.get("x-forwarded-for");
  return createClient<paths>({
    baseUrl: backendUrl,
    headers: {
      cookie: (await cookies()).toString(),
      ...(id && { [REQUEST_ID_HEADER]: id }),
      ...(forwardedFor && { "x-forwarded-for": forwardedFor }),
    },
  });
}
