import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ForgotPasswordForm } from "@/components/account-forms";
import { getLoginOptions } from "@/lib/auth";

export const instant = false;

export const metadata: Metadata = { title: "Forgot your password" };

// The form brings its own AuthCard: the title changes once the link is sent.
export default async function ForgotPasswordPage() {
  if (!(await getLoginOptions())?.password_reset) notFound();
  return <ForgotPasswordForm />;
}
