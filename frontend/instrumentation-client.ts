import * as Sentry from "@sentry/nextjs";
import { SENTRY_TUNNEL_PATH, sentryOptions } from "@/lib/sentry";

// The browser's SDK. Its events go to /monitoring on this origin, where the
// server's SDK (serveTunnelIntegration in instrumentation.ts) passes them on to
// Sentry: same origin, so the CSP stays connect-src 'self' and ad blockers
// don't drop them. Calls to /api carry the trace in the sentry-trace and
// baggage headers, so Django joins the trace.
Sentry.init({ ...sentryOptions, tunnel: { path: SENTRY_TUNNEL_PATH } });

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
