import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LoginLinkForm, UseLoginLink } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { getLoginOptions } from "@/lib/auth";
import { nextPath } from "@/lib/next-path";

export const instant = false;

export const metadata: Metadata = { title: "Log in with a link" };

// Asks for the link (/login-link?next=...), and is where the link in the
// email goes (/login-link?uid=...&token=...&next=...).
export default async function LoginLinkPage({
  searchParams,
}: PageProps<"/login-link">) {
  const { uid, token, next: rawNext } = await searchParams;
  if (!(await getLoginOptions())?.magic_link) notFound();
  const next = nextPath(rawNext);
  if (typeof uid === "string" && typeof token === "string")
    return (
      <AuthCard title="Log in" description="Use the link from your email">
        <UseLoginLink uid={uid} token={token} next={next} />
      </AuthCard>
    );
  return (
    <AuthCard
      title="Log in with a link"
      description="We will email you a link that logs you in"
    >
      <LoginLinkForm next={next} standalone />
    </AuthCard>
  );
}
