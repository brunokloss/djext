// Headers on every response from Next: its pages, and what the rewrites in
// next.config.ts bring from Django (the API, and the admin when it's proxied).
//
// The CSP allows inline scripts and styles: Next puts some in every page, and
// with cacheComponents a page's static shell is built ahead of time, so it
// can't carry a per-request nonce (see Next's guide, "Content Security
// Policy"). Everything else comes from this origin only. A page that needs a
// third party (analytics, a CDN, images from a provider) adds it here.

// `bucket`: the S3 bucket's address (STORAGE_BUCKET_URL), which the browser
// talks to directly: images from it, and uploads and downloads with fetch.
export function contentSecurityPolicy(dev: boolean, bucket = ""): string {
  const files = bucket ? ` ${bucket}` : "";
  return [
    "default-src 'self'",
    // React's development build uses eval for its error overlay.
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' blob: data:${files}`,
    "font-src 'self'",
    `connect-src 'self'${files}`,
    "object-src 'none'",
    "base-uri 'self'",
    // Where forms may post. The OAuth buttons are links, not forms.
    "form-action 'self'",
    // No other site may show these pages in a frame (clickjacking).
    "frame-ancestors 'none'",
  ].join("; ");
}

// HTTPS only, for a year: once a browser has seen it over HTTPS, it never
// sends a request to this host over plain HTTP again (where a network could
// read the session cookie or keep the visitor on HTTP). Browsers ignore it
// over HTTP, so http://localhost is safe; still, development doesn't send it.
// Only this host: subdomains (includeSubDomains) may not all have HTTPS.
export const HSTS = "max-age=31536000";

export function securityHeaders(dev: boolean, bucket = "") {
  const hsts = dev ? [] : [{ key: "Strict-Transport-Security", value: HSTS }];
  return [
    ...hsts,
    {
      key: "Content-Security-Policy",
      value: contentSecurityPolicy(dev, bucket),
    },
    // The same as frame-ancestors, for browsers that only know this one.
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    // Other sites see the origin, never the path (it may hold a ?next= or an id).
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    // Nothing here uses them; a page that does turns its own on.
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    },
    // A page opened from here can't reach back through window.opener.
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ];
}
