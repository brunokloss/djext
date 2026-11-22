import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

// Self-service accounts (backend/modules/signup). Skipped when the backend
// has them off (AUTH_SIGNUP, AUTH_PASSWORD_RESET): playwright.config.ts turns
// them on for the backend it starts, not for a `make dev` it reuses.
test.beforeEach(async ({ request }) => {
  const options = await (await request.get("/api/auth/providers")).json();
  test.skip(!options.signup || !options.password_reset, "sign-up is off");
});

// The link in the last email queued for `to`, as the worker would send it.
function lastLink(to: string): string {
  const code = `from post_office.models import Email
email = Email.objects.filter(to__icontains=${JSON.stringify(to)}).latest("id")
print(email.context["url"])`;
  const url = execFileSync(
    "uv",
    ["run", "python", "manage.py", "shell", "-v", "0", "-c", code],
    { cwd: "../backend", encoding: "utf8" },
  ).trim();
  const { pathname, search } = new URL(url);
  return pathname + search;
}

async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

test("sign up, confirm the email and log in", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const password = "a-long-e2e-password";
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign up" }).click();
  await expect(page).toHaveURL("/signup");
  await page.getByLabel("First name").fill("Eve");
  await page.getByLabel("Last name").fill("Adams");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  // A typo shows while typing, and the button waits.
  await page.getByLabel("Confirm password").fill("a-typo");
  await expect(page.getByText("The passwords don't match")).toBeVisible();
  // Submitted anyway: nothing is sent, and the focus goes there.
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByLabel("Confirm password")).toBeFocused();
  await page.getByLabel("Confirm password").fill(password);
  await expect(page.getByText("The passwords don't match")).toBeHidden();
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByText("Check your email")).toBeVisible();

  // Not active yet.
  await login(page, email, password);
  await expect(page.getByText("We sent a new link")).toBeVisible();

  // Opening the link confirms it and lands on the login, the email filled in
  // and the notice's query gone.
  const verify = lastLink(email);
  await page.goto(verify);
  await expect(page.getByText("Your account is confirmed")).toBeVisible();
  await expect(page).toHaveURL("/login");
  await expect(page.getByLabel("Email")).toHaveValue(email);
  await expect(page.getByLabel("Password")).toBeFocused();

  // Opened again: confirmed already, the same landing.
  await page.goto(verify);
  await expect(page.getByText("Your account is confirmed")).toBeVisible();

  await login(page, email, password);
  await expect(page).toHaveURL("/");
});

test("forgot the password and choose a new one", async ({ page }) => {
  // A user of its own: the other tests log in as the seeded ones.
  const email = `e2e-reset-${Date.now()}@example.com`;
  execFileSync(
    "uv",
    [
      "run",
      "python",
      "manage.py",
      "shell",
      "-v",
      "0",
      "-c",
      `from django.contrib.auth import get_user_model
get_user_model().objects.create_user(email=${JSON.stringify(email)}, password="old-password")`,
    ],
    { cwd: "../backend" },
  );
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  // Else the email goes into /login's field, before the page changes.
  await expect(page).toHaveURL("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send the reset link" }).click();
  await expect(page.getByText("We sent a link to")).toBeVisible();

  const link = lastLink(email);
  await page.goto(link);
  await page
    .getByLabel("New password", { exact: true })
    .fill("a-brand-new-password");
  await page
    .getByLabel("Confirm the new password")
    .fill("a-brand-new-password");
  await page.getByRole("button", { name: "Save the password" }).click();
  await expect(page.getByText("Your password was changed")).toBeVisible();
  await expect(page).toHaveURL("/login");
  await expect(page.getByLabel("Email")).toHaveValue(email);

  // The link works once: opened again, it says so before asking.
  await page.goto(link);
  await expect(page.getByText("used already")).toBeVisible();
  await expect(page.getByLabel("New password", { exact: true })).toBeHidden();

  await login(page, email, "a-brand-new-password");
  await expect(page).toHaveURL("/");
});
