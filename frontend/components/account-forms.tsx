"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, useState } from "react";
import { AuthCard } from "@/components/auth-card";
import { LOGIN_EMAIL_KEY } from "@/components/login-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";

// The forms of the self-service pages (backend/modules/signup): sign up,
// verify the email, forgot and reset the password. Each posts from the
// browser through the Next proxy, like the login form. The ones that send an
// email get the same answer whether the email has an account or not.

type State = { error?: string; done?: boolean };

// The login page fills it in after a confirmation or a reset (LoginForm).
function rememberLoginEmail(email: string) {
  sessionStorage.setItem(LOGIN_EMAIL_KEY, email);
}

// A labelled input. Its message goes under it, tied to it for screen
// readers: `error` from the form, or a wrong email found on leaving the field
// (cleared while typing). `hint` says the rule before anyone breaks it.
function Field({
  id,
  label,
  error,
  hint,
  onBlur,
  onChange,
  ...props
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
} & React.ComponentProps<typeof Input>) {
  const [invalid, setInvalid] = useState<string>();
  const message = error ?? invalid;
  const note = message ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={id}
        required
        aria-invalid={message ? true : undefined}
        aria-describedby={note}
        onBlur={(e) => {
          if (e.target.validity.typeMismatch)
            setInvalid("Enter a valid email.");
          onBlur?.(e);
        }}
        onChange={(e) => {
          setInvalid(undefined);
          onChange?.(e);
        }}
        {...props}
      />
      {message ? (
        <p id={note} className="text-sm text-destructive">
          {message}
        </p>
      ) : (
        hint && (
          <p id={note} className="text-sm text-muted-foreground">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

// The password typed twice, so a typo doesn't lock the person out. Checked
// while typing: the second one is wrong as soon as it stops matching the
// start of the first, or on leaving it. check() runs on submit: it says so
// and moves the focus there. Controlled, so a refused password (too weak)
// keeps both.
function usePasswordPair() {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [left, setLeft] = useState(false);
  const confirm = useRef<HTMLInputElement>(null);
  const wrong =
    again !== "" && (left ? again !== password : !password.startsWith(again));
  return {
    password,
    check: () => {
      if (password === again) return true;
      setLeft(true);
      confirm.current?.focus();
      return false;
    },
    fields: (labels: [string, string], autoFocus = false) => (
      <>
        <Field
          id="password"
          label={labels[0]}
          type="password"
          autoComplete="new-password"
          hint="At least 8 characters, not only numbers."
          autoFocus={autoFocus}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          id="password2"
          label={labels[1]}
          type="password"
          autoComplete="new-password"
          ref={confirm}
          error={wrong ? "The passwords don't match." : undefined}
          value={again}
          onChange={(e) => setAgain(e.target.value)}
          onBlur={() => setLeft(true)}
        />
      </>
    ),
  };
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

// After a link was sent: where it went, how long it works, and a way to send
// it again (after a minute) or, on sign-up, to fix the address.
function CheckEmail({
  email,
  resend,
  onChangeEmail,
}: {
  email: string;
  resend: () => Promise<string | undefined>;
  onChangeEmail?: () => void;
}) {
  const [wait, setWait] = useState(60);
  const [note, setNote] = useState<string>();
  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);
  return (
    <>
      <p role="status" className="text-center text-sm">
        We sent a link to <strong>{email}</strong>. It expires in 1 hour. Not
        there? Check your spam.
      </p>
      {note && (
        <p role="status" className="text-center text-sm text-muted-foreground">
          {note}
        </p>
      )}
      <Button
        variant="outline"
        disabled={wait > 0}
        onClick={async () => {
          const error = await resend();
          setNote(error ?? "Sent again.");
          setWait(60);
        }}
      >
        {wait > 0 ? `Resend the email (${wait}s)` : "Resend the email"}
      </Button>
      {onChangeEmail && (
        <Button variant="ghost" onClick={onChangeEmail}>
          Use a different email
        </Button>
      )}
      <BackToLogin />
    </>
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
  const pair = usePasswordPair();
  const [sent, setSent] = useState(false);
  const [state, signup, pending] = useActionState(async (): Promise<State> => {
    if (!pair.check()) return {};
    const { error } = await api.POST("/api/auth/signup", {
      body: {
        email: values.email,
        password: pair.password,
        first_name: values.name,
        last_name: "",
      },
    });
    if (error) return { error: error.detail };
    setSent(true);
    return {};
  }, {});
  if (sent)
    return (
      <AuthCard title="Check your email">
        <CheckEmail
          email={values.email}
          resend={async () => {
            const { error } = await api.POST("/api/auth/verify/resend", {
              body: { email: values.email },
            });
            return error?.detail;
          }}
          onChangeEmail={() => setSent(false)}
        />
      </AuthCard>
    );

  return (
    <AuthCard title="Sign up" description="Create your account">
      <form action={signup} className="flex flex-col gap-4">
        <Field
          id="name"
          autoFocus
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
        {pair.fields(["Password", "Confirm password"])}
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
    </AuthCard>
  );
}

// Opening the link confirms the account and goes to the login, also when it
// was confirmed already (the link opened again). A dead link offers a new one.
export function VerifyEmail({ uid, token }: { uid: string; token: string }) {
  const router = useRouter();
  const [error, setError] = useState<string>();
  // Once: React runs effects twice in development, and a second post would
  // find the link used.
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    api
      .POST("/api/auth/verify", { body: { uid, token } })
      .then(({ data, error }) => {
        if (error) return setError(error.detail);
        rememberLoginEmail(data.email);
        router.replace("/login?verified=1");
      });
  }, [uid, token, router]);

  if (!error)
    return (
      <p className="text-center text-sm text-muted-foreground">
        Confirming your email…
      </p>
    );
  return (
    <>
      <Alert error={error} />
      <EmailLinkForm
        path="/api/auth/verify/resend"
        button="Send a new link"
        sent={(email) =>
          `If ${email} is waiting for its confirmation, a new link is on its way.`
        }
      />
      <BackToLogin />
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
  const [email, setEmail] = useState("");
  const send = async () => {
    const { error } = await api.POST("/api/auth/password/forgot", {
      body: { email },
    });
    return error?.detail;
  };
  const [state, ask, pending] = useActionState(async (): Promise<State> => {
    const error = await send();
    return error ? { error } : { done: true };
  }, {});
  if (state.done)
    return (
      <AuthCard title="Check your email">
        <CheckEmail email={email} resend={send} />
      </AuthCard>
    );

  return (
    <AuthCard
      title="Forgot your password?"
      description="We will email you a link to choose a new one"
    >
      <form action={ask} className="flex flex-col gap-4">
        <Field
          id="email"
          autoFocus
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Alert error={state.error} />
        <Button type="submit" disabled={pending}>
          {pending ? "Sending…" : "Send the reset link"}
        </Button>
      </form>
      <BackToLogin />
    </AuthCard>
  );
}

// Checks the link first, so a dead one says so before asking for a password,
// and offers a new one.
export function ResetPasswordForm({
  uid,
  token,
}: {
  uid: string;
  token: string;
}) {
  const router = useRouter();
  const pair = usePasswordPair();
  const [alive, setAlive] = useState<boolean>();
  useEffect(() => {
    api
      .POST("/api/auth/password/reset/check", { body: { uid, token } })
      .then(({ response }) => setAlive(response.ok));
  }, [uid, token]);
  const [state, reset, pending] = useActionState(async (): Promise<State> => {
    if (!pair.check()) return {};
    const { data, error, response } = await api.POST(
      "/api/auth/password/reset",
      {
        body: { uid, token, password: pair.password },
      },
    );
    if (response.status === 410) setAlive(false);
    if (error) return { error: error.detail };
    rememberLoginEmail(data.email);
    router.replace("/login?reset=1");
    return { done: true };
  }, {});

  if (alive === undefined) return null;
  if (!alive)
    return (
      <>
        <Alert error="This link is invalid, expired or used already." />
        <EmailLinkForm
          path="/api/auth/password/forgot"
          button="Send a new link"
          sent={(email) =>
            `If ${email} has an account, a link to choose a new password is on its way.`
          }
        />
        <BackToLogin />
      </>
    );
  return (
    <form action={reset} className="flex flex-col gap-4">
      {pair.fields(["New password", "Confirm the new password"], true)}
      <Alert error={state.error} />
      <Button type="submit" disabled={pending || state.done}>
        {pending ? "Saving…" : "Save the password"}
      </Button>
    </form>
  );
}
