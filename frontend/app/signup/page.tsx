import { notFound, redirect } from "next/navigation";
import { SignupForm } from "@/components/account-forms";
import { AuthCard } from "@/components/auth-card";
import { getCurrentUser, getLoginOptions } from "@/lib/auth";

// Blocks on the session check, like the login page.
export const instant = false;

export default async function SignupPage() {
  if (!(await getLoginOptions())?.signup) notFound();
  if (await getCurrentUser()) redirect("/");
  return (
    <AuthCard title="Sign up" description="Create your account">
      <SignupForm />
    </AuthCard>
  );
}
