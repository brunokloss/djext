import { notFound, redirect } from "next/navigation";
import { SignupForm } from "@/components/account-forms";
import { getCurrentUser, getLoginOptions } from "@/lib/auth";

// Blocks on the session check, like the login page.
export const instant = false;

// The form brings its own AuthCard: the title changes once the link is sent.
export default async function SignupPage() {
  if (!(await getLoginOptions())?.signup) notFound();
  if (await getCurrentUser()) redirect("/");
  return <SignupForm />;
}
