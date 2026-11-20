import { withSentryConfig } from "@sentry/nextjs/config";
import type { NextConfig } from "next";
import { backendUrl } from "./lib/api/backend-url";
import { securityHeaders } from "./lib/security-headers";

// Requests to /api are proxied to the backend, so the browser only ever talks
// to the Next origin (no CORS needed). The admin is opened on Django itself.

// The S3 bucket's address, the one Django signs file URLs for: the browser
// downloads and uploads there directly, so the CSP allows it. Empty with files
// on disk.
const storageBucketUrl = (process.env.STORAGE_BUCKET_URL ?? "").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  // frontend/Dockerfile builds a self-contained server (.next/standalone);
  // Vercel and `next start` don't need it.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  // Some of Django's URLs end with a slash. Next would 308 them to the
  // slashless form and Django would redirect back, looping forever.
  skipTrailingSlashRedirect: true,
  // proxy.ts logs every request in the same format as Django (lib/log.ts);
  // Next's own `GET / 200 in 61ms` line would be a second, different one.
  logging: { incomingRequests: false },
  // No "X-Powered-By: Next.js": it only tells attackers what to try.
  poweredByHeader: false,
  headers() {
    const dev = process.env.NODE_ENV === "development";
    return Promise.resolve([
      {
        source: "/:path*",
        headers: securityHeaders(dev, storageBucketUrl),
      },
    ]);
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  rewrites() {
    // `:path(.*)` instead of `:path*` keeps the trailing slash Django expects.
    return Promise.resolve([
      { source: "/api/:path(.*)", destination: `${backendUrl}/api/:path` },
      // The API docs (/api/docs) load Swagger UI's CSS and JS from Django's
      // static files. Only these: the admin is opened on Django itself.
      {
        source: "/static/ninja/:path*",
        destination: `${backendUrl}/static/ninja/:path*`,
      },
    ]);
  },
};

export default withSentryConfig(nextConfig, {
  // Source maps are uploaded on `next build` only when these are set (a
  // self-hosted Sentry also needs SENTRY_URL). Without them, stack traces show
  // the minified code.
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sentryUrl: process.env.SENTRY_URL,
  silent: !process.env.CI,
  telemetry: false,
});
