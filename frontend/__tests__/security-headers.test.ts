import { expect, test } from "vitest";
import { contentSecurityPolicy, securityHeaders } from "@/lib/security-headers";

test("nothing from other origins, no frames, no plugins", () => {
  const csp = contentSecurityPolicy(false);
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("object-src 'none'");
  expect(csp).not.toContain("https:");
});

test("the bucket only when the browser talks to it directly", () => {
  const csp = contentSecurityPolicy(false, "https://files.s3.amazonaws.com");
  expect(csp).toContain(
    "img-src 'self' blob: data: https://files.s3.amazonaws.com",
  );
  expect(csp).toContain("connect-src 'self' https://files.s3.amazonaws.com");
});

test("eval only in development", () => {
  expect(contentSecurityPolicy(false)).not.toContain("unsafe-eval");
  expect(contentSecurityPolicy(true)).toContain("'unsafe-eval'");
});

test("HTTPS only (HSTS) outside development", () => {
  const hsts = (dev: boolean) =>
    securityHeaders(dev).find((h) => h.key === "Strict-Transport-Security");
  expect(hsts(false)?.value).toBe("max-age=31536000");
  expect(hsts(true)).toBeUndefined();
});

test("the usual hardening headers", () => {
  const keys = securityHeaders(false).map((header) => header.key);
  expect(keys).toEqual(
    expect.arrayContaining([
      "Content-Security-Policy",
      "X-Frame-Options",
      "X-Content-Type-Options",
      "Referrer-Policy",
      "Permissions-Policy",
    ]),
  );
});
