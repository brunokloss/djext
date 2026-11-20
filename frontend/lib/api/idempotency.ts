"use client";

import { useState } from "react";

// backend/modules/idempotency: an `@idempotent` endpoint that gets the same key
// twice answers the first response again instead of running twice. So a
// retry (a timeout, a double click) can't create the thing twice.
export const IDEMPOTENCY_HEADER = "Idempotency-Key";

// Worth retrying with the same key: still running (409), the server failed
// (5xx, the key was freed) or no answer at all (no response).
function retryable(response?: Response) {
  return !response || response.status === 409 || response.status >= 500;
}

// One key per action the user means to do (a form, a button). Send `headers`
// with the request; call `settle` with its response: any final answer gets a
// new key for the next action, so a corrected form isn't taken for a retry
// (the server answers 422 to the same key with another body).
//
//   const idem = useIdempotencyKey();
//   const { response } = await api.POST("/api/things", { body, headers: idem.headers });
//   idem.settle(response);
export function useIdempotencyKey() {
  const [key, setKey] = useState(() => crypto.randomUUID());
  return {
    key,
    headers: { [IDEMPOTENCY_HEADER]: key },
    settle(response?: Response) {
      if (!retryable(response)) setKey(crypto.randomUUID());
    },
  };
}
