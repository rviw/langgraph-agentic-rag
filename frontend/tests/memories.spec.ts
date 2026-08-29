import { expect, test } from "@playwright/test";

import { stubApi } from "./support/api.ts";
import { signIn, stubSupabaseAuth } from "./support/supabase.ts";

const memory = (id: string, content: string) => ({
  id,
  content,
  created_at: "2026-08-29T00:00:00Z",
});

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page);
  await signIn(page);
});

test("the memories screen is reachable from the chat sidebar", async ({ page }) => {
  await stubApi(page, { memories: [memory("m1", "The user prefers Python.")] });

  await page.goto("/chats");
  await page.getByRole("link", { name: "Memories" }).click();

  await expect(page).toHaveURL(/\/memories$/);
  await expect(page.getByRole("heading", { name: "Memories" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Saved memories" })).toContainText(
    "The user prefers Python.",
  );
});

test("one memory can be forgotten", async ({ page }) => {
  const stub = await stubApi(page, {
    memories: [
      memory("m1", "The user prefers Python."),
      memory("m2", "The user is in Seoul."),
    ],
  });

  await page.goto("/memories");
  await page
    .getByRole("button", { name: "Delete memory: The user prefers Python." })
    .click();

  await expect(page.getByRole("list", { name: "Saved memories" })).not.toContainText(
    "The user prefers Python.",
  );
  await expect(page.getByRole("list", { name: "Saved memories" })).toContainText(
    "The user is in Seoul.",
  );
  expect(stub.requests).toContain("DELETE /memories/m1");
});

test("an account with no memories explains what will appear", async ({ page }) => {
  await stubApi(page, { memories: [] });

  await page.goto("/memories");

  await expect(page.getByText("No saved memories")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete all" })).toBeDisabled();
});

test("all memories are forgotten only after the dialog is confirmed", async ({
  page,
}) => {
  const stub = await stubApi(page, {
    memories: [memory("m1", "First fact."), memory("m2", "Second fact.")],
  });

  await page.goto("/memories");
  await page.getByRole("button", { name: "Delete all" }).click();
  await page.getByRole("button", { name: "Cancel" }).click();
  expect(stub.requests).not.toContain("DELETE /memories/");

  await page.getByRole("button", { name: "Delete all" }).click();
  await page.getByRole("button", { name: "Delete all memories" }).click();

  await expect(page.getByText("No saved memories")).toBeVisible();
  expect(stub.requests).toContain("DELETE /memories/");
});

test("a failed load can be retried", async ({ page }) => {
  const stub = await stubApi(page, {
    memoryStatus: { status: 500, detail: "unavailable" },
  });

  await page.goto("/memories");
  await expect(page.getByRole("alert")).toContainText(
    "Couldn’t load saved memories. Try again.",
  );

  stub.memoryStatus = undefined;
  stub.memories = [memory("m1", "Recovered fact.")];
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByRole("list", { name: "Saved memories" })).toContainText(
    "Recovered fact.",
  );
});
