import { expect, test } from "@playwright/test";

test("the root path lands on the chat area", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/chats$/);
  await expect(
    page.getByRole("heading", { name: "LangGraph Agentic RAG" }),
  ).toBeVisible();
});

test("an unknown path shows the not-found page", async ({ page }) => {
  await page.goto("/does-not-exist");

  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Go to chats" }).click();

  await expect(page).toHaveURL(/\/chats$/);
});

test("the theme toggle switches the document theme", async ({ page }) => {
  await page.goto("/chats");

  const toggle = page.getByRole("button", { name: /switch to (dark|light) theme/i });
  const wasDark = await page.evaluate(() =>
    document.documentElement.classList.contains("dark"),
  );
  await toggle.click();

  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.classList.contains("dark")),
    )
    .toBe(!wasDark);
});
