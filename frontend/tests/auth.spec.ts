import { expect, test, type Page } from "@playwright/test";

import { stubApi } from "./support/api.ts";
import { signIn, stubSupabaseAuth } from "./support/supabase.ts";

test.beforeEach(async ({ page }) => {
  await stubApi(page);
});

const submit = (page: Page) => page.locator("button[type=submit]");
const switchMode = (page: Page) =>
  page.locator("footer").getByRole("button");

async function fillCredentials(page: Page, password = "Password-1234") {
  await page.locator("input[name=email]").fill("member@example.test");
  await page.locator("input[name=password]").fill(password);
}

test("a protected route sends a visitor to sign in and back again", async ({
  page,
}) => {
  await stubSupabaseAuth(page);

  await page.goto("/chats");
  await expect(page).toHaveURL(/\/login$/);

  await fillCredentials(page);
  await submit(page).click();

  await expect(page).toHaveURL(/\/chats$/);
});

test("account creation is blocked until the disclosure is accepted", async ({
  page,
}) => {
  const calls = await stubSupabaseAuth(page);
  await page.goto("/login");
  await switchMode(page).click();

  await fillCredentials(page);
  await expect(page.getByText(/may be sent to OpenAI/)).toBeVisible();
  await expect(submit(page)).toBeDisabled();
  expect(calls.filter((call) => call.path === "/signup")).toHaveLength(0);

  await page
    .getByRole("checkbox", {
      name: "I agree to the external provider disclosure and data processing described above.",
    })
    .check();
  await expect(submit(page)).toBeEnabled();
  await submit(page).click();

  await expect(page).toHaveURL(/\/chats$/);
  expect(calls.filter((call) => call.path === "/signup")).toHaveLength(1);
});

test("a rejected sign-in shows one recoverable message", async ({ page }) => {
  await page.route("**/supabase/auth/v1/token**", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ error: "invalid_grant" }),
    });
  });

  await page.goto("/login");
  await fillCredentials(page, "wrong-password");
  await submit(page).click();

  await expect(page.getByRole("alert")).toContainText(
    "Couldn't sign in. Check your email and password.",
  );
  await expect(page).toHaveURL(/\/login$/);
});

test("an authenticated visitor is redirected away from sign in", async ({
  page,
}) => {
  await stubSupabaseAuth(page);
  await signIn(page);

  await page.goto("/login");

  await expect(page).toHaveURL(/\/chats$/);
});
