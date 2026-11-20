import { expect, type Page, test } from "@playwright/test";
import { SESSION_COOKIE } from "@/lib/login-guard";

async function login(
  page: Page,
  password = "password",
  url = "/login",
  email = "ana@example.com",
) {
  await page.goto(url);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

test("anonymous visit to / redirects to /login", async ({ request }) => {
  const response = await request.get("/", { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe("/login");
});

test("wrong password shows an error and keeps the email", async ({ page }) => {
  await login(page, "wrong");
  await expect(page.getByText("Invalid email or password")).toBeVisible();
  await expect(page).toHaveURL("/login");
  await expect(page.getByLabel("Email")).toHaveValue("ana@example.com");
  await expect(page.getByLabel("Password")).toHaveValue("");
});

test("login shows the user from the server and from the browser", async ({
  page,
}) => {
  await login(page);
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("user-server")).toHaveText(
    "From the server: ana@example.com",
  );
  await expect(page.getByTestId("user-client")).toHaveText(
    "From the browser: ana@example.com",
  );
});

test("the browser calls the API through the Next proxy", async ({ page }) => {
  const me = page.waitForResponse("**/api/users/me");
  await login(page);
  expect(new URL((await me).url()).port).toBe("3000");
});

test("a logged-in visit to /login goes to /", async ({ page }) => {
  await login(page);
  await expect(page).toHaveURL("/");
  // A real 307 from proxy.ts, not a redirect in the browser.
  const response = await page.request.get("/login?next=/api/docs", {
    maxRedirects: 0,
  });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe("/api/docs");
  await page.goto("/login");
  await expect(page).toHaveURL("/");
});

test("a stale session cookie on /login shows the page", async ({ request }) => {
  const response = await request.get("/login", {
    headers: { cookie: `${SESSION_COOKIE}=stale` },
    maxRedirects: 0,
  });
  expect(response.status()).toBe(200);
});

test("logout ends the session", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
  await page.goto("/");
  await expect(page).toHaveURL("/login");
});

test("API docs require login and come back after it", async ({ page }) => {
  await page.goto("/api/docs");
  await expect(page).toHaveURL("/login?next=/api/docs");
  await login(page, "password", "/login?next=/api/docs");
  await expect(page).toHaveURL("/api/docs");
  // Swagger UI rendered the endpoints: its CSS and JS loaded through Next.
  await expect(page.locator(".opblock").first()).toBeVisible();
});

test("API is reachable through the Next proxy", async ({ request }) => {
  const response = await request.get("/api/health");
  expect(response.ok()).toBe(true);
  expect(await response.json()).toMatchObject({ status: "ok" });
});

test("every page gets a request id", async ({ request }) => {
  // proxy.ts keeps a valid incoming id, or makes one.
  const kept = await request.get("/login", {
    headers: { "X-Request-Id": "e2e-trace-0001" },
  });
  expect(kept.headers()["x-request-id"]).toBe("e2e-trace-0001");
  const fresh = await request.get("/login");
  expect(fresh.headers()["x-request-id"]).toMatch(/^[0-9a-f]{8}$/);
});

test("the request id reaches Django", async ({ request }) => {
  // On /api the response is Django's: backend/modules/log sends
  // back the id it got from proxy.ts. Without that module there is none.
  const response = await request.get("/api/health", {
    headers: { "X-Request-Id": "e2e-trace-0002" },
  });
  const id = response.headers()["x-request-id"];
  test.skip(id === undefined, "log is off");
  expect(id).toBe("e2e-trace-0002");
});

test("only staff see the Admin link", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");

  await login(page, "password", "/login", "admin@example.com");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveAttribute(
    "href",
    "http://localhost:8000/admin/",
  );
});
