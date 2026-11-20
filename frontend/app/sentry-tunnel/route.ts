// The tunnel of tunnelRoute (next.config.ts): /monitoring is rewritten here
// (the SDK looks for this exact path). Forwards the browser's Sentry
// events to the DSN, without the request's headers (cookies stay here).
export { POST } from "@sentry/nextjs/tunnel";
