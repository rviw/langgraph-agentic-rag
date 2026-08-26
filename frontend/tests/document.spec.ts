import { expect, test, type Page } from "@playwright/test";

import { sseBody, stubApi, type StubDocument } from "./support/api.ts";
import { signIn, stubSupabaseAuth } from "./support/supabase.ts";

const PDF_BYTES = Buffer.from("%PDF-1.7\nsmall test document\n");

const document = (overrides: Partial<StubDocument> = {}): StubDocument => ({
  id: "document-1",
  original_filename: "report.pdf",
  media_type: "application/pdf",
  size_bytes: PDF_BYTES.length,
  status: "ready",
  indexing_error_code: null,
  created_at: "2026-08-26T00:00:00Z",
  ...overrides,
});

async function attach(page: Page) {
  await page.locator("input[name=document]").setInputFiles({
    name: "report.pdf",
    mimeType: "application/pdf",
    buffer: PDF_BYTES,
  });
}

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page);
  await signIn(page);
});

test("an attached PDF is uploaded, confirmed, and reported ready", async ({
  page,
}) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    confirmedStatus: "ready",
  });

  await page.goto("/chats/chat-1");
  await attach(page);

  await expect(page.getByRole("list", { name: "Document" })).toContainText(
    "report.pdf",
  );
  await expect(page.getByText("Document ready")).toBeVisible();
  expect(stub.requests).toContain("POST /chat-1/document");
  expect(stub.requests).toContain("POST /chat-1/document/confirm-upload");
});

test("a ready document cannot be removed", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    document: document({ status: "ready" }),
  });

  await page.goto("/chats/chat-1");

  await expect(page.getByText("Document ready")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove report.pdf" }),
  ).toBeHidden();
});

test("a chat with a document offers no second attachment", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    document: document({ status: "ready" }),
  });

  await page.goto("/chats/chat-1");

  await expect(page.getByText("Document ready")).toBeVisible();
  await expect(page.getByRole("button", { name: "Attach PDF" })).toBeHidden();
});

test("sending is held until the document finishes indexing", async ({ page }) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    document: document({ status: "indexing" }),
    stream: sseBody([
      {
        event: "message.accepted",
        data: { message: { id: "m1", role: "user", content: "Question", citations: [] } },
      },
      {
        event: "message.completed",
        data: { message: { id: "m2", role: "assistant", content: "An answer.", citations: [] } },
      },
    ]),
  });

  await page.goto("/chats/chat-1");
  await page.getByRole("textbox", { name: "Message" }).fill("Question");

  const send = page.getByRole("button", { name: "Send message" });
  await expect(page.getByText("Processing document…")).toBeVisible();
  await expect(send).toBeDisabled();

  // The screen polls, so making the document ready must release the gate.
  stub.document = document({ status: "ready" });
  await expect(send).toBeEnabled();
  await send.click();

  await expect(page.getByRole("article", { name: "Assistant" })).toHaveText(
    "An answer.",
  );
});

test("a document that could not be read explains itself and can be removed", async ({
  page,
}) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    document: document({
      status: "indexing_failed",
      indexing_error_code: "invalid_pdf",
    }),
  });

  await page.goto("/chats/chat-1");

  await expect(page.getByText("Couldn’t read this document.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();

  await page.getByRole("button", { name: "Remove report.pdf" }).click();

  await expect(page.getByRole("list", { name: "Document" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Attach PDF" })).toBeVisible();
  expect(stub.requests).toContain("DELETE /chat-1/document");
});

test("a failed Storage upload leaves a removable incomplete document", async ({
  page,
}) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
  });
  await page.route("**/supabase/storage/v1/**", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ message: "storage unavailable" }),
    });
  });

  await page.goto("/chats/chat-1");
  await attach(page);

  // The reservation exists but no bytes arrived, so the upload never confirms.
  await expect(page.getByText("Upload incomplete.")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Couldn’t upload this document. Try again.",
  );
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  expect(stub.requests).not.toContain("POST /chat-1/document/confirm-upload");

  await page.getByRole("button", { name: "Remove report.pdf" }).click();

  await expect(page.getByRole("button", { name: "Attach PDF" })).toBeVisible();
  await expect(page.getByRole("alert")).toBeHidden();
});
