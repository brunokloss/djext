"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { useClearApiCache } from "@/lib/api/hooks";

// An email another page leaves for the login to fill in (the sign-up module,
// after a confirmation or a reset). sessionStorage, not the URL: an email
// doesn't belong in history or logs.
export const LOGIN_EMAIL_KEY = "login-email";

// Posts from the browser through the Next proxy, so Django sets the session
// cookie on the Next origin.
export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const clearApiCache = useClearApiCache();
  // Controlled, because React resets the form after the action: on a failed
  // login the email stays.
  const [email, setEmail] = useState("");
  // Controlled too: kept when the password was right (403, the email is not
  // confirmed yet), cleared when it was wrong.
  const [password, setPassword] = useState("");
  const passwordInput = useRef<HTMLInputElement>(null);
  // After a confirmation or a reset (components/account-forms.tsx): the email
  // is filled in, and the notice's ?verified=1 / ?reset=1 leaves the URL so a
  // reload doesn't show it again.
  useEffect(() => {
    const remembered = sessionStorage.getItem(LOGIN_EMAIL_KEY);
    if (remembered) {
      sessionStorage.removeItem(LOGIN_EMAIL_KEY);
      setEmail(remembered);
      passwordInput.current?.focus();
    }
    const url = new URL(window.location.href);
    if (url.searchParams.has("verified") || url.searchParams.has("reset")) {
      url.searchParams.delete("verified");
      url.searchParams.delete("reset");
      window.history.replaceState(window.history.state, "", url);
    }
  }, []);
  const [error, login, pending] = useActionState(
    async (_previous: string | null) => {
      const { error, response } = await api.POST("/api/auth/login", {
        body: { email, password },
      });
      if (error) {
        if (response.status !== 403) setPassword("");
        return error.detail;
      }
      await clearApiCache();
      // `next` may be a Django page (like /api/docs) the Next router doesn't
      // know, so load it in full.
      if (next) window.location.assign(next);
      else router.replace("/");
      return null;
    },
    null,
  );

  return (
    <form action={login} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          ref={passwordInput}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending}>
        {pending ? "Logging in…" : "Log in"}
      </Button>
    </form>
  );
}
