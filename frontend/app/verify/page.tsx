import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { VerifyEmail } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { getLoginOptions } from "@/lib/auth";

export const instant = false;

export const metadata: Metadata = { title: "Confirm your email" };

// The link in the sign-up email: /verify?uid=...&token=...
export default async function VerifyPage({
  searchParams,
}: PageProps<"/verify">) {
  const { uid, token } = await searchParams;
  if (!(await getLoginOptions())?.signup) notFound();
  if (typeof uid !== "string" || typeof token !== "string") notFound();
  return (
    <AuthCard title="Confirm your email">
      <VerifyEmail uid={uid} token={token} />
    </AuthCard>
  );
}
