"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { useClearApiCache } from "@/lib/api/hooks";

// Posts from the browser through the Next proxy, so Django sets the session
// cookie on the Next origin.
export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const clearApiCache = useClearApiCache();
  // Controlled, because React resets the form after the action: on a failed
  // login the email stays and only the password is cleared.
  const [email, setEmail] = useState("");
  const [error, login, pending] = useActionState(
    async (_previous: string | null, form: FormData) => {
      const { error } = await api.POST("/api/auth/login", {
        body: {
          email,
          password: String(form.get("password")),
        },
      });
      if (error) return error.detail;
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
