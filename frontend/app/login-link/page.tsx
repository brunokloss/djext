import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { UseLoginLink } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { getLoginOptions } from "@/lib/auth";
import { nextPath } from "@/lib/next-path";

export const instant = false;

export const metadata: Metadata = { title: "Log in" };

// Where the link in the email goes: /login-link?uid=...&token=...&next=...
// The link is asked for on /login.
export default async function LoginLinkPage({
  searchParams,
}: PageProps<"/login-link">) {
  const { uid, token, next: rawNext } = await searchParams;
  if (!(await getLoginOptions())?.magic_link) notFound();
  const next = nextPath(rawNext);
  if (typeof uid !== "string" || typeof token !== "string")
    redirect(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
  return (
    <AuthCard title="Log in" description="Use the link from your email">
      <UseLoginLink uid={uid} token={token} next={next} />
    </AuthCard>
  );
}
