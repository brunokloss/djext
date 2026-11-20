import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";
import { IDEMPOTENCY_HEADER, useIdempotencyKey } from "@/lib/api/idempotency";

function answer(status: number) {
  return new Response(null, { status });
}

test("sends one key until there is a final answer", () => {
  const { result } = renderHook(() => useIdempotencyKey());
  const first = result.current.key;
  expect(result.current.headers[IDEMPOTENCY_HEADER]).toBe(first);

  // Retries keep the key: no answer, still running, server error.
  for (const response of [undefined, answer(409), answer(503)]) {
    act(() => result.current.settle(response));
    expect(result.current.key).toBe(first);
  }

  act(() => result.current.settle(answer(201)));
  expect(result.current.key).not.toBe(first);
});

test("a 4xx is final too: the corrected form gets a new key", () => {
  const { result } = renderHook(() => useIdempotencyKey());
  const first = result.current.key;
  act(() => result.current.settle(answer(400)));
  expect(result.current.key).not.toBe(first);
});
