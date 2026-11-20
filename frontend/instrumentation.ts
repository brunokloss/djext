import * as Sentry from "@sentry/nextjs";
import type { Instrumentation } from "next";
import { log } from "@/lib/log";
import { REQUEST_ID_HEADER } from "@/lib/request-id";
import { SENTRY_TUNNEL_PATH, sentryOptions } from "@/lib/sentry";

// The server's SDK (Node and the edge runtime): rendering errors, the server's
// part of each trace, and the tunnel the browser sends its events through.
export function register() {
  Sentry.init({
    ...sentryOptions,
    integrations: [Sentry.serveTunnelIntegration({ path: SENTRY_TUNNEL_PATH })],
  });
}

// Server errors (rendering, route handlers, proxy): to Sentry, and on the
// error channel with the request id from proxy.ts.
export const onRequestError: Instrumentation.onRequestError = async (
  error,
  request,
  context,
) => {
  Sentry.captureRequestError(error, request, context);
  const id = request.headers[REQUEST_ID_HEADER];
  log("error", "error", `${request.method} ${request.path}`, {
    request_id: typeof id === "string" ? id : undefined,
    error: error instanceof Error ? error.message : String(error),
    // Production hides the message from the browser and shows this instead.
    digest:
      typeof error === "object" && error !== null && "digest" in error
        ? String(error.digest)
        : undefined,
    stack: error instanceof Error ? error.stack : undefined,
    route: context.routePath,
  });
};
