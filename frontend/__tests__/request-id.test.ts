import { expect, test } from "vitest";
import { requestId } from "@/lib/request-id";

test("keeps an incoming id that looks like one", () => {
  expect(requestId("from-the-lb-1234")).toBe("from-the-lb-1234");
});

test("makes a new one otherwise", () => {
  for (const value of [null, undefined, "", "short", "evil id\nnewline"]) {
    expect(requestId(value)).toMatch(/^[0-9a-f]{8}$/);
  }
});
