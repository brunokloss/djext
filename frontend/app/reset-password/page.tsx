import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ResetPasswordForm } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { getLoginOptions } from "@/lib/auth";

export const instant = false;

export const metadata: Metadata = { title: "Choose a new password" };

// The link in the password reset email: /reset-password?uid=...&token=...
export default async function ResetPasswordPage({
  searchParams,
}: PageProps<"/reset-password">) {
  const { uid, token } = await searchParams;
  if (!(await getLoginOptions())?.password_reset) notFound();
  if (typeof uid !== "string" || typeof token !== "string") notFound();
  return (
    <AuthCard title="Choose a new password">
      <ResetPasswordForm uid={uid} token={token} />
    </AuthCard>
  );
}
