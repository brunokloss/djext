import { expect, type Page, test } from "@playwright/test";

// Logging in with a provider (backend/modules/oauth), through the mock one
// (`manage.py oauth_mock`, which logs in as any email typed in). Skipped when
// the backend doesn't offer it: the module is gone, or AUTH_MOCK_URL is empty.
test.beforeEach(async ({ request }) => {
  const options = await (await request.get("/api/auth/providers")).json();
  const names = options.providers.map((p: { name: string }) => p.name);
  test.skip(!names.includes("mock"), "the mock provider is off");
});

test("the login page shows the providers that are on", async ({
  page,
  request,
}) => {
  const options = await (await request.get("/api/auth/providers")).json();
  await page.goto("/login");
  for (const { label } of options.providers) {
    await expect(
      page.getByRole("link", { name: `Continue with ${label}` }),
    ).toHaveCount(1);
  }
});

async function loginWithMock(page: Page, email: string, url = "/login") {
  await page.goto(url);
  await page.getByRole("link", { name: "Continue with Mock" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Continue" }).click();
}

test("login with a provider", async ({ page }) => {
  await loginWithMock(page, "ana@example.com", "/login?next=/api/docs");
  await expect(page).toHaveURL("/api/docs");
  await page.goto("/");
  await expect(page.getByTestId("user-server")).toHaveText(
    "From the server: ana@example.com",
  );
});

test("login with a provider needs an existing account", async ({ page }) => {
  await loginWithMock(page, "nobody@example.com");
  await expect(page).toHaveURL("/login?error=oauth_no_account");
  await expect(
    page.getByText("There is no account with this email."),
  ).toBeVisible();
});
