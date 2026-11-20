"use client";

import { useSyncExternalStore } from "react";

const noop = () => () => {};

// A date and time in the browser's locale and time zone, which the server
// doesn't know. The server renders it in UTC; the browser switches to its
// own right after hydration.
export function LocalTime({ value }: { value: string }) {
  const local = useSyncExternalStore(
    noop,
    () => new Date(value).toLocaleString(),
    () => null,
  );
  return (
    <time dateTime={value}>
      {local ?? `${value.slice(0, 16).replace("T", " ")} UTC`}
    </time>
  );
}
