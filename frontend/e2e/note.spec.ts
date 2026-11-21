import { expect, test } from "@playwright/test";

// The example feature (backend/apps/note), end to end: delete with it.
test("add, email and delete a note", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("ana@example.com");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL("/");

  await page.getByRole("link", { name: "Notes" }).click();
  const title = `Groceries ${Date.now()}`;
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Text").fill("milk");
  await page.getByRole("button", { name: "Add note" }).click();

  const card = page.locator("[data-slot=card]", { hasText: title });
  await expect(card).toContainText("milk");
  await card.getByRole("button", { name: "Email me" }).click();
  await expect(card.getByRole("button", { name: "Emailed" })).toBeVisible();
  await card.getByRole("button", { name: "Delete" }).click();
  await expect(card).toHaveCount(0);
});
