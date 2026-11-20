import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AppSidebar } from "@/components/app-sidebar";
import { Separator } from "@/components/ui/separator";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { adminUrl } from "@/lib/admin";
import { getCurrentUser } from "@/lib/auth";
import { projectName } from "@/lib/project";

// The pages behind login. Blocks on the session check, so an anonymous visit
// gets a real redirect instead of a shell that streams in.
export const instant = false;

export default async function AppLayout({ children }: LayoutProps<"/">) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  // The sidebar remembers being open or closed in this cookie.
  const open = (await cookies()).get("sidebar_state")?.value !== "false";

  return (
    <SidebarProvider defaultOpen={open}>
      <AppSidebar
        name={user.first_name || user.email}
        email={user.email}
        adminHref={user.is_staff && adminUrl ? adminUrl : undefined}
      />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator
            orientation="vertical"
            className="mr-2 data-vertical:h-4 data-vertical:self-center"
          />
          <span className="text-sm font-medium">{projectName}</span>
        </header>
        <div className="flex flex-1 flex-col gap-6 p-6">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}
