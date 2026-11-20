import { CurrentUserClient } from "@/components/current-user-client";
import { SentryTestCard } from "@/components/sentry-test-card";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getCurrentUser } from "@/lib/auth";

export const instant = false;

export default async function Home() {
  // The layout already sent anonymous visits to /login.
  const user = await getCurrentUser();
  if (!user) return null;

  return (
    <>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Hello, {user.first_name || user.email}
        </h1>
        <p className="text-sm text-muted-foreground">
          This is the start page. Replace it with your app.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Server Component</CardTitle>
            <CardDescription>
              Read on the server, before the page is sent.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p data-testid="user-server">From the server: {user.email}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Client Component</CardTitle>
            <CardDescription>
              Fetched in the browser with useApi (SWR).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CurrentUserClient />
          </CardContent>
        </Card>
        <SentryTestCard />
      </div>
    </>
  );
}
