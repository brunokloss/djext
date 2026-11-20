import { expect, test } from "vitest";
import { nextPath } from "@/lib/next-path";

test("accepts same-origin paths", () => {
  expect(nextPath("/api/docs")).toBe("/api/docs");
  expect(nextPath("/")).toBe("/");
  expect(nextPath("/a?b=c#d")).toBe("/a?b=c#d");
});

test("rejects anything that could leave the site", () => {
  for (const value of [
    "//evil.com",
    "//[",
    "/\\evil.com",
    "/\t/evil.com",
    "/\n/evil.com",
    "/\r/evil.com",
    decodeURIComponent("/%5Cevil.com"),
    decodeURIComponent("/%09/evil.com"),
    "https://evil.com",
    "evil",
    "",
    undefined,
  ]) {
    expect(nextPath(value)).toBeUndefined();
  }
  expect(nextPath(["/a", "/b"])).toBeUndefined();
});

test("rejects backslash tricks from a ?next= query string", () => {
  const next = new URLSearchParams("next=/%5Cevil.com").get("next");
  expect(nextPath(next ?? undefined)).toBeUndefined();
});
