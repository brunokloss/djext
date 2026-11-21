"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";

// The forms of the self-service pages (backend/modules/signup): sign up,
// verify the email, forgot and reset the password. Each posts from the
// browser through the Next proxy, like the login form. The ones that send an
// email get the same answer whether the email has an account or not.

type State = { error?: string; done?: boolean };

function Field({
  id,
  label,
  ...props
}: { id: string; label: string } & React.ComponentProps<typeof Input>) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} required {...props} />
    </div>
  );
}

function Alert({ error }: { error?: string }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {error}
    </p>
  );
}

function Done({ children }: { children: React.ReactNode }) {
  return (
    <p role="status" className="text-center text-sm">
      {children}
    </p>
  );
}

function BackToLogin() {
  return (
    <Link
      href="/login"
      className="text-center text-sm underline-offset-4 hover:underline"
    >
      Back to log in
    </Link>
  );
}

export function SignupForm() {
  // Controlled, so a refused password keeps what was typed in the others.
  const [values, setValues] = useState({ name: "", email: "" });
  const [state, signup, pending] = useActionState(
    async (_previous: State, form: FormData): Promise<State> => {
      const { error } = await api.POST("/api/auth/signup", {
        body: {
          email: values.email,
          password: String(form.get("password")),
          first_name: values.name,
          last_name: "",
        },
      });
      return error ? { error: error.detail } : { done: true };
    },
    {},
  );
  if (state.done)
    return (
      <>
        <Done>
          Check your email: we sent a link to {values.email} to activate your
          account.
        </Done>
        <BackToLogin />
      </>
    );

  return (
    <form action={signup} className="flex flex-col gap-4">
      <Field
        id="name"
        label="Name"
        autoComplete="given-name"
        value={values.name}
        onChange={(e) => setValues({ ...values, name: e.target.value })}
      />
      <Field
        id="email"
        label="Email"
        type="email"
        autoComplete="email"
        value={values.email}
        onChange={(e) => setValues({ ...values, email: e.target.value })}
      />
      <Field
        id="password"
        label="Password"
        type="password"
        autoComplete="new-password"
      />
      <Alert error={state.error} />
      <Button type="submit" disabled={pending}>
        {pending ? "Signing up…" : "Sign up"}
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        Have an account?{" "}
        <Link
          href="/login"
          className="text-foreground underline-offset-4 hover:underline"
        >
          Log in
        </Link>
      </p>
    </form>
  );
}

// A button, not a request on page load: mail scanners open links, and must
// not use them up. Once confirmed it goes to the login. A dead link offers a
// new one.
export function VerifyEmail({ uid, token }: { uid: string; token: string }) {
  const router = useRouter();
  const [state, verify, pending] = useActionState(async (): Promise<State> => {
    const { error } = await api.POST("/api/auth/verify", {
      body: { uid, token },
    });
    if (error) return { error: error.detail };
    router.push("/login?verified=1");
    return { done: true };
  }, {});

  return (
    <>
      <form action={verify} className="flex flex-col gap-4">
        <Alert error={state.error} />
        <Button type="submit" disabled={pending || state.done}>
          {pending ? "Confirming…" : "Confirm my email"}
        </Button>
      </form>
      {state.error && (
        <EmailLinkForm
          path="/api/auth/verify/resend"
          button="Send a new link"
          sent={(email) =>
            `If ${email} is waiting for its confirmation, a new link is on its way.`
          }
        />
      )}
    </>
  );
}

// Asks for an email and has a link sent to it. The answer is the same
// whether the email has an account or not.
function EmailLinkForm({
  path,
  button,
  sent,
}: {
  path: "/api/auth/password/forgot" | "/api/auth/verify/resend";
  button: string;
  sent: (email: string) => string;
}) {
  const [email, setEmail] = useState("");
  const [state, send, pending] = useActionState(async (): Promise<State> => {
    const { error } = await api.POST(path, { body: { email } });
    return error ? { error: error.detail } : { done: true };
  }, {});
  if (state.done) return <Done>{sent(email)}</Done>;

  return (
    <form action={send} className="flex flex-col gap-4">
      <Field
        id="email"
        label="Email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Alert error={state.error} />
      <Button type="submit" disabled={pending}>
        {pending ? "Sending…" : button}
      </Button>
    </form>
  );
}

export function ForgotPasswordForm() {
  return (
    <>
      <EmailLinkForm
        path="/api/auth/password/forgot"
        button="Send the link"
        sent={(email) =>
          `If ${email} has an account, a link to choose a new password is on its way.`
        }
      />
      <BackToLogin />
    </>
  );
}

export function ResetPasswordForm({
  uid,
  token,
}: {
  uid: string;
  token: string;
}) {
  const [state, reset, pending] = useActionState(
    async (_previous: State, form: FormData): Promise<State> => {
      const { error } = await api.POST("/api/auth/password/reset", {
        body: { uid, token, password: String(form.get("password")) },
      });
      return error ? { error: error.detail } : { done: true };
    },
    {},
  );
  if (state.done)
    return (
      <>
        <Done>Your password was changed. Log in with the new one.</Done>
        <Link href="/login" className="text-center text-sm underline">
          Log in
        </Link>
      </>
    );

  return (
    <form action={reset} className="flex flex-col gap-4">
      <Field
        id="password"
        label="New password"
        type="password"
        autoComplete="new-password"
      />
      <Alert error={state.error} />
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Save the password"}
      </Button>
    </form>
  );
}
