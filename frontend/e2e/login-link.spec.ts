import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

// Log in with a link by email (backend/modules/signup). Skipped unless the
// backend has it on, which takes the password off (AUTH_PASSWORD=False,
// AUTH_MAGIC_LINK=True): the other tests log in with the password, so run
// this one against a `make dev` set up that way.
test.beforeEach(async ({ request }) => {
  const options = await (await request.get("/api/auth/providers")).json();
  test.skip(!options.magic_link, "the login link is off");
});

function django(code: string): string {
  return execFileSync(
    "uv",
    ["run", "python", "manage.py", "shell", "-v", "0", "-c", code],
    { cwd: "../backend", encoding: "utf8" },
  ).trim();
}

// The link in the last email queued for `to`, as the worker would send it.
function lastLink(to: string): string {
  const { pathname, search } = new URL(
    django(`from post_office.models import Email
print(Email.objects.filter(to__icontains=${JSON.stringify(to)}).latest("id").context["url"])`),
  );
  return pathname + search;
}

test("a link by email logs in once and goes to next", async ({ page }) => {
  // A new user each run, so the per-address email limit never gets in the
  // way, and without a password: the link is all they need.
  const email = `e2e-link-${Date.now()}@example.com`;
  django(`from django.contrib.auth import get_user_model
get_user_model().objects.create_user(email=${JSON.stringify(email)})`);

  // On the login page itself: the email and the button, no password.
  await page.goto("/login?next=/notes");
  await expect(page.getByLabel("Password")).toHaveCount(0);
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Email me a login link" }).click();
  await expect(page.getByText(`We sent a link to ${email}`)).toBeVisible();

  // Opening the link doesn't log in (a mail scanner may open it): the button
  // does.
  const link = lastLink(email);
  await page.goto(link);
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL("/notes");

  // Used: a second time it offers a new one.
  await page.context().clearCookies();
  await page.goto(link);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(
    page.getByText("invalid, expired or used already"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Email me a login link" }),
  ).toBeVisible();
});
