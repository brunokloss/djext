"use client";

import * as Sentry from "@sentry/nextjs";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { useApi } from "@/lib/api/hooks";

// Superusers only: a click that breaks Django on purpose (POST
// /api/debug/error). In Sentry the click, the API call and Django's error show
// up in one trace, with the browser's error next to Django's.
export function SentryTestCard() {
  const { data: me } = useApi("/api/users/me");
  const [result, setResult] = useState<string>();
  if (!me?.is_superuser) return null;

  async function sendTestError() {
    setResult("sending…");
    // A new trace for this click; the API call below joins it, and Django
    // continues it from the sentry-trace and baggage headers.
    const status = await Sentry.startNewTrace(() =>
      Sentry.startSpan(
        {
          name: "Send test error",
          op: "ui.action.click",
          forceTransaction: true,
        },
        async (span) => {
          const { response } = await api.POST("/api/debug/error");
          return `${response.status}, trace ${span.spanContext().traceId}`;
        },
      ),
    );
    setResult(`Django answered ${status}`);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sentry</CardTitle>
        <CardDescription>
          Breaks the API on purpose, to check that the error reaches Sentry from
          both sides, in the same trace.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-2">
        <Button variant="destructive" onClick={sendTestError}>
          Send test error
        </Button>
        {result && (
          <p
            className="text-sm text-muted-foreground"
            data-testid="sentry-result"
          >
            {result}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
