import { CircleCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { LoginLinkForm } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { LoginForm } from "@/components/login-form";
import { buttonVariants } from "@/components/ui/button";
import { serverApi } from "@/lib/api/server";
import { getCurrentUser } from "@/lib/auth";
import { nextPath } from "@/lib/next-path";
import { cn } from "@/lib/utils";

// Blocks on the session check, like the home page.
export const instant = false;

export const metadata: Metadata = { title: "Log in" };

// Set by the backend when logging in with a provider fails (modules/oauth).
// Unused if that module is gone.
const OAUTH_ERRORS: Record<string, string> = {
  oauth_not_configured: "This way to log in is not configured.",
  oauth_cancelled: "Login was cancelled.",
  oauth_invalid_state: "Login expired. Try again.",
  oauth_failed: "Could not reach the provider. Try again.",
  oauth_unverified_email: "The provider did not confirm your email.",
  oauth_no_account: "There is no account with this email.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = nextPath(params.next);
  if (await getCurrentUser()) redirect(next ?? "/");
  // The ways to log in that are on: the password and whatever the backend's
  // modules add (each with its label and where to start it).
  const { data: options } = await (await serverApi()).GET(
    "/api/auth/providers",
  );
  const error =
    typeof params.error === "string" ? OAUTH_ERRORS[params.error] : undefined;
  const notice =
    params.verified === "1"
      ? "Your account is confirmed. Log in to continue."
      : params.reset === "1"
        ? "Your password was changed. Log in with the new one."
        : undefined;
  // A full navigation, not fetch: the backend redirects to the provider and
  // back.
  const query = next ? `?next=${encodeURIComponent(next)}` : "";

  return (
    <AuthCard title="Log in" description="Welcome back">
      {/* From /verify and /reset-password (modules/signup). */}
      {notice && !error && (
        <p
          role="status"
          className="flex items-center gap-2 rounded-lg border border-emerald-600/30 bg-emerald-600/10 p-3 text-sm text-emerald-700 dark:text-emerald-400"
        >
          <CircleCheck className="size-4 shrink-0" />
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {options?.providers.map((option) => (
        <a
          key={option.name}
          href={`${option.url}${query}`}
          className={cn(buttonVariants({ variant: "outline" }))}
        >
          Continue with {option.label}
        </a>
      ))}
      {options?.providers.length && (options.password || options.magic_link) ? (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>
      ) : null}
      {options?.password && <LoginForm next={next} />}
      {/* A login link by email instead of the password
          (backend/modules/signup), off by default. */}
      {options?.magic_link && <LoginLinkForm next={next} />}
      {/* Self-service accounts (backend/modules/signup), off by default. */}
      {options?.password_reset && (
        <Link
          href="/forgot-password"
          className="text-center text-sm underline-offset-4 hover:underline"
        >
          Forgot your password?
        </Link>
      )}
      {options?.signup && (
        <p className="text-center text-sm text-muted-foreground">
          No account yet?{" "}
          <Link
            href="/signup"
            className="text-foreground underline-offset-4 hover:underline"
          >
            Sign up
          </Link>
        </p>
      )}
    </AuthCard>
  );
}
