import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "@/lib/sentry";

// The browser's SDK. Its events go to /monitoring on this origin (tunnelRoute
// in next.config.ts), which passes them on to Sentry. Calls to /api carry the
// trace in the sentry-trace and baggage headers, so Django joins the trace.
Sentry.init(sentryOptions);

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
