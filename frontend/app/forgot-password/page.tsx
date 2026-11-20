import { notFound } from "next/navigation";
import { ForgotPasswordForm } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { getLoginOptions } from "@/lib/auth";

export const instant = false;

export default async function ForgotPasswordPage() {
  if (!(await getLoginOptions())?.password_reset) notFound();
  return (
    <AuthCard
      title="Forgot your password?"
      description="We will email you a link to choose a new one"
    >
      <ForgotPasswordForm />
    </AuthCard>
  );
}
