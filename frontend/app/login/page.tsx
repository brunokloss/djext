import { Boxes } from "lucide-react";
import { redirect } from "next/navigation";
import { LoginForm } from "@/components/login-form";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { serverApi } from "@/lib/api/server";
import { getCurrentUser } from "@/lib/auth";
import { nextPath } from "@/lib/next-path";
import { projectName } from "@/lib/project";
import { cn } from "@/lib/utils";

// Blocks on the session check, like the home page.
export const instant = false;

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
  // A full navigation, not fetch: the backend redirects to the provider and
  // back.
  const query = next ? `?next=${encodeURIComponent(next)}` : "";

  return (
    <main className="grid flex-1 lg:grid-cols-2">
      <div className="flex flex-col items-center justify-center gap-6 bg-muted p-6 md:p-10">
        <div className="flex items-center gap-2 font-semibold">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Boxes className="size-4" />
          </div>
          {projectName}
        </div>
        <Card className="w-full max-w-sm">
          <CardHeader className="text-center">
            <CardTitle>
              <h1 className="text-xl">Log in</h1>
            </CardTitle>
            <CardDescription>Welcome back</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
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
            {options?.providers.length && options.password ? (
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="h-px flex-1 bg-border" />
                or
                <span className="h-px flex-1 bg-border" />
              </div>
            ) : null}
            {options?.password && <LoginForm next={next} />}
          </CardContent>
        </Card>
      </div>
      {/* Brand panel, only on wide screens and dark in both themes. Swap it for your own art. */}
      <div className="relative hidden overflow-hidden bg-neutral-950 text-neutral-50 lg:flex lg:flex-col lg:justify-end lg:p-10">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,oklch(1_0_0/12%),transparent_55%),radial-gradient(circle_at_80%_80%,oklch(1_0_0/8%),transparent_50%)]" />
        <blockquote className="relative max-w-md space-y-2">
          <p className="text-lg">
            Django for the API and the admin, Next.js for the screens.
          </p>
          <footer className="text-sm opacity-70">{projectName}</footer>
        </blockquote>
      </div>
    </main>
  );
}
