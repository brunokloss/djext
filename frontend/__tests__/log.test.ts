import { stripVTControlCharacters } from "node:util";
import { afterEach, expect, test, vi } from "vitest";
import { log } from "@/lib/log";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

test("production: one JSON line with the backend's fields", () => {
  vi.stubEnv("NODE_ENV", "production");
  const print = vi.spyOn(console, "log").mockImplementation(() => {});
  log("info", "request", "GET /", { request_id: "abcd1234" });
  expect(JSON.parse(print.mock.calls[0][0])).toMatchObject({
    event: "GET /",
    level: "info",
    request_id: "abcd1234",
    service: "frontend",
    channel: "request",
  });
});

test("development: colored columns, like the backend", () => {
  vi.stubEnv("NODE_ENV", "development");
  const print = vi.spyOn(console, "log").mockImplementation(() => {});
  log("warning", "request", "GET /", { request_id: "abcd1234", route: "/" });
  // Without the colors: time, [level], channel, id, event, key=value.
  const plain = stripVTControlCharacters(print.mock.calls[0][0]);
  expect(plain).toMatch(
    /^\S+Z \[warning {2}\] request {2}abcd1234 {2}GET \/ +route=\/$/,
  );
});
