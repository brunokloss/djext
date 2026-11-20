// Options shared by the browser and the server SDKs (instrumentation-client.ts
// and instrumentation.ts). Sentry is off while NEXT_PUBLIC_SENTRY_DSN is empty.
// NEXT_PUBLIC_ values are read at build time: set them before `next build`.
export const sentryOptions = {
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN || undefined,
  environment:
    process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
    (process.env.NODE_ENV === "production" ? "production" : "development"),
  // Share of traces kept. The browser decides for each click or page load, and
  // Django follows its decision, so both sides of a trace are kept together.
  tracesSampleRate: Number(
    process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? 1,
  ),
  // No user, IPs, cookies or request bodies leave for Sentry (LGPD).
  sendDefaultPii: false,
};
