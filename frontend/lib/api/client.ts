import * as Sentry from "@sentry/nextjs";
import createClient from "openapi-fetch";
import { REQUEST_ID_HEADER } from "@/lib/request-id";
import { backendUrl } from "./backend-url";
import { csrfToken } from "./csrf";
import type { components, paths } from "./schema";

export type User = components["schemas"]["UserOut"];
// The logged-in user, with their groups and permissions (/api/users/me).
export type Me = components["schemas"]["MeOut"];

const isBrowser = typeof window !== "undefined";

// On the server we call Django directly. In the browser we use relative URLs,
// which go through the Next proxy (same origin, so cookies and CSRF just work).
const baseUrl = isBrowser ? "" : backendUrl;

export const api = createClient<paths>({ baseUrl });

// Django rejects browser POST/PUT/PATCH/DELETE without the CSRF token, so add
// it to every one of them.
if (isBrowser) {
  api.use({
    async onRequest({ request }) {
      if (request.method === "GET" || request.method === "HEAD") return;
      request.headers.set("X-CSRFToken", await csrfToken());
      return request;
    },
  });
}

// A 5xx from Django goes to Sentry from the browser too: Django reports the
// error itself, and this one ties it to what the user was doing (the click's
// trace). The request id leads to both sides' logs.
export class ApiError extends Error {
  name = "ApiError";
}

if (isBrowser) {
  api.use({
    onResponse({ request, response }) {
      if (response.status < 500) return;
      const path = new URL(request.url).pathname;
      Sentry.captureException(
        new ApiError(`${request.method} ${path} answered ${response.status}`),
        {
          tags: { request_id: response.headers.get(REQUEST_ID_HEADER) },
          fingerprint: [
            "api-error",
            request.method,
            path,
            `${response.status}`,
          ],
        },
      );
    },
  });
}
