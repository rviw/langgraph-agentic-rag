import { expect, test } from "@playwright/test";

import { sseBody, stubApi } from "./support/api.ts";
import { signIn, stubSupabaseAuth } from "./support/supabase.ts";

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page);
  await signIn(page);
});

test("sending a message shows progress and then the answer", async ({ page }) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    // A heartbeat between frames proves the reader ignores comment lines.
    stream: sseBody([
      {
        event: "message.accepted",
        data: { message: { id: "m1", role: "user", content: "What is RAG?", citations: [] } },
      },
      { event: "execution.progress", data: { phase: "understanding" } },
      { comment: true },
      { event: "execution.progress", data: { phase: "searching" } },
      {
        event: "message.completed",
        data: {
          message: {
            id: "m2",
            role: "assistant",
            content: "Retrieval augmented generation grounds answers.",
            citations: [],
          },
        },
      },
    ]),
  });

  await page.goto("/chats/chat-1");
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("What is RAG?");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("article", { name: "You" })).toHaveText(
    "What is RAG?",
  );
  await expect(page.getByRole("article", { name: "Assistant" })).toHaveText(
    "Retrieval augmented generation grounds answers.",
  );
  await expect(box).toHaveValue("");
  expect(stub.requests).toContain("POST /chat-1/messages");
});

test("a failed answer keeps the text and offers a retry", async ({ page }) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    stream: sseBody([
      {
        event: "message.accepted",
        data: { message: { id: "m1", role: "user", content: "Question", citations: [] } },
      },
      {
        event: "execution.failed",
        data: { error: { message: "Couldn’t generate a response." } },
      },
    ]),
  });

  await page.goto("/chats/chat-1");
  await page.getByRole("textbox", { name: "Message" }).fill("Question");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("alert")).toContainText(
    "Couldn’t generate a response.",
  );

  stub.stream = sseBody([
    {
      event: "message.accepted",
      data: { message: { id: "m1", role: "user", content: "Question", citations: [] } },
    },
    {
      event: "message.completed",
      data: { message: { id: "m2", role: "assistant", content: "An answer.", citations: [] } },
    },
  ]);
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByRole("article", { name: "Assistant" })).toHaveText(
    "An answer.",
  );
  await expect(page.getByRole("alert")).toBeHidden();
});

test("a rejected request shows the server's own message", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "New chat" }],
    streamStatus: { status: 404, detail: "This chat is no longer available." },
  });

  await page.goto("/chats/chat-1");
  await page.getByRole("textbox", { name: "Message" }).fill("Question");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("alert")).toContainText(
    "This chat is no longer available.",
  );
});

test("stored messages are restored when a chat is opened", async ({ page }) => {
  await stubApi(page, {
    chats: [{ id: "chat-1", title: "Earlier chat" }],
    messages: [
      { id: "m1", role: "user", content: "Earlier question", citations: [] },
      { id: "m2", role: "assistant", content: "Earlier answer", citations: [] },
    ],
  });

  await page.goto("/chats/chat-1");

  await expect(page.getByRole("article", { name: "You" })).toHaveText(
    "Earlier question",
  );
  await expect(page.getByRole("article", { name: "Assistant" })).toHaveText(
    "Earlier answer",
  );
});

test("a new chat is created and opened from the sidebar", async ({ page }) => {
  const stub = await stubApi(page);

  await page.goto("/chats");
  await expect(page.getByText("No chats yet")).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();

  await expect(page).toHaveURL(/\/chats\/chat-1$/);
  expect(stub.requests).toContain("POST /");
});

test("a chat is deleted only after the dialog is confirmed", async ({ page }) => {
  const stub = await stubApi(page, {
    chats: [{ id: "chat-1", title: "Disposable chat" }],
  });

  await page.goto("/chats");
  await page.getByRole("button", { name: "Delete Disposable chat" }).click();
  await page.getByRole("button", { name: "Cancel" }).click();
  expect(stub.requests).not.toContain("DELETE /chat-1");

  await page.getByRole("button", { name: "Delete Disposable chat" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();

  await expect(page.getByText("No chats yet")).toBeVisible();
  expect(stub.requests).toContain("DELETE /chat-1");
});

test("a failed chat list can be retried", async ({ page }) => {
  const stub = await stubApi(page, {
    listStatus: { status: 500, detail: "unavailable" },
  });

  await page.goto("/chats");
  await expect(page.getByRole("alert")).toContainText(
    "Couldn’t load chats. Try again.",
  );

  stub.listStatus = undefined;
  stub.chats = [{ id: "chat-1", title: "Recovered chat" }];
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByRole("link", { name: "Recovered chat" })).toBeVisible();
});
