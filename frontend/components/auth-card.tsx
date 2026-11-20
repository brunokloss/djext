import { Boxes } from "lucide-react";
import type { ReactNode } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { projectName } from "@/lib/project";

// The frame of the pages people see logged out (log in, sign up, reset the
// password): a card on the left, the brand panel on the right.
export function AuthCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
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
              <h1 className="text-xl">{title}</h1>
            </CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </CardHeader>
          <CardContent className="flex flex-col gap-4">{children}</CardContent>
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
