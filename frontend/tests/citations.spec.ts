import { expect, test } from "@playwright/test";

import { stubApi } from "./support/api.ts";
import { signIn, stubSupabaseAuth } from "./support/supabase.ts";

const documentCitation = {
  source_id: "11111111-1111-4111-8111-111111111111",
  type: "document" as const,
  document_id: "22222222-2222-4222-8222-222222222222",
  chunk_id: "33333333-3333-4333-8333-333333333333",
  chunk_index: 1,
  filename: "report.pdf",
  page: 2,
  excerpt: "Retrieval augmented generation grounds answers in sources.",
};

const webCitation = {
  source_id: "44444444-4444-4444-8444-444444444444",
  type: "web" as const,
  title: "Vector search overview",
  url: "https://example.test/vector-search",
  excerpt: "Vector search compares embeddings.",
};

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page);
  await signIn(page);
});

test("embedded HTML and unsafe links are not rendered", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "Earlier chat" }],
    messages: [
      {
        id: "m1",
        role: "assistant",
        content:
          "<img src=x onerror=\"window.pwned=1\"> <script>window.pwned=1</script>\n\n[click me](javascript:window.pwned=1)",
        citations: [],
      },
    ],
  });

  await page.goto("/chats/chat-1");
  const answer = page.getByRole("article", { name: "Assistant" });
  await expect(answer).toBeVisible();

  // No script ran, no image element was created, and the link is inert.
  expect(await page.evaluate(() => "pwned" in window)).toBe(false);
  await expect(answer.locator("img")).toHaveCount(0);
  await expect(answer.locator("script")).toHaveCount(0);
  await expect(answer.getByRole("link", { name: "click me" })).toHaveCount(0);
  await expect(answer).toContainText("click me");
});

test("a document citation opens its passage and adjacent context", async ({
  page,
}) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "Earlier chat" }],
    messages: [
      {
        id: "m1",
        role: "assistant",
        content: "Grounded claim [1].",
        citations: [documentCitation],
      },
    ],
    sourceDetail: {
      ...documentCitation,
      context: [
        {
          chunk_id: "55555555-5555-4555-8555-555555555555",
          chunk_index: 0,
          page: 1,
          excerpt: "Earlier passage for context.",
        },
      ],
    },
  });

  await page.goto("/chats/chat-1");
  await page.getByRole("button", { name: "View source 1" }).click();

  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("Source [1]");
  await expect(drawer).toContainText("report.pdf");
  await expect(drawer).toContainText("Page 2 · Cited passage");
  await expect(drawer).toContainText("Page 1 · Adjacent context");

  await page.getByRole("button", { name: "Close source details" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.getByRole("button", { name: "View source 1" })).toBeFocused();
});

test("a web citation opens the stored snapshot and its link", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "Earlier chat" }],
    messages: [
      {
        id: "m1",
        role: "assistant",
        content: "Current information [1].",
        citations: [webCitation],
      },
    ],
    sourceDetail: webCitation,
  });

  await page.goto("/chats/chat-1");
  await page.getByRole("button", { name: "View source 1" }).click();

  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("Vector search overview");
  await expect(drawer.getByRole("link", { name: /Open original source/ })).toHaveAttribute(
    "href",
    "https://example.test/vector-search",
  );
});

test("a marker with no matching citation stays plain text", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "Earlier chat" }],
    messages: [
      {
        id: "m1",
        role: "assistant",
        content: "Claim [1] and invented marker [7].",
        citations: [documentCitation],
      },
    ],
  });

  await page.goto("/chats/chat-1");

  await expect(page.getByRole("button", { name: "View source 1" })).toBeVisible();
  await expect(page.getByRole("button", { name: "View source 7" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Assistant" })).toContainText("[7]");
});

test("a source that cannot be loaded reports the failure", async ({ page }) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "Earlier chat" }],
    messages: [
      {
        id: "m1",
        role: "assistant",
        content: "Grounded claim [1].",
        citations: [documentCitation],
      },
    ],
    sourceDetail: null,
  });

  await page.goto("/chats/chat-1");
  await page.getByRole("button", { name: "View source 1" }).click();

  await expect(page.getByRole("alert")).toContainText(
    "This source is no longer available.",
  );
  stub.sourceDetail = { ...documentCitation, context: [] };
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Page 2 · Cited passage");
  await expect(page.getByRole("alert")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("button", { name: "View source 1" })).toBeFocused();
});
