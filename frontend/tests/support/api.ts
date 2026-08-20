import type { Page, Route } from "@playwright/test";

export type StubChat = {
  id: string;
  title: string;
  created_at?: string;
};

export type StubMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

/** Render server-sent events exactly as the backend frames them. */
export function sseBody(
  events: ({ event: string; data: unknown } | { comment: true })[],
): string {
  return events
    .map((entry) =>
      "comment" in entry
        ? ": heartbeat\n\n"
        : `event: ${entry.event}\ndata: ${JSON.stringify(entry.data)}\n\n`,
    )
    .join("");
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export type ApiStub = {
  chats: StubChat[];
  messages: StubMessage[];
  /** Frames returned for the next sent message. */
  stream: string;
  /** Status returned instead of the stream, when set. */
  streamStatus?: { status: number; detail: string };
  listStatus?: { status: number; detail: string };
  requests: string[];
};

export async function stubApi(page: Page, initial: Partial<ApiStub> = {}) {
  const stub: ApiStub = {
    chats: initial.chats ?? [],
    messages: initial.messages ?? [],
    stream: initial.stream ?? "",
    streamStatus: initial.streamStatus,
    listStatus: initial.listStatus,
    requests: [],
  };

  await page.route("**/api/chats**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/chats", "");
    stub.requests.push(`${request.method()} ${path || "/"}`);

    if (request.method() === "GET" && path === "") {
      if (stub.listStatus) {
        await json(route, { detail: stub.listStatus.detail }, stub.listStatus.status);
        return;
      }
      await json(
        route,
        stub.chats.map((chat) => ({
          created_at: "2026-08-20T00:00:00Z",
          ...chat,
        })),
      );
      return;
    }

    if (request.method() === "POST" && path === "") {
      const chat = {
        id: `chat-${stub.chats.length + 1}`,
        title: "New chat",
        created_at: "2026-08-20T00:00:00Z",
      };
      stub.chats = [chat, ...stub.chats];
      await json(route, chat, 201);
      return;
    }

    if (request.method() === "POST" && path.endsWith("/messages")) {
      if (stub.streamStatus) {
        await json(
          route,
          { detail: stub.streamStatus.detail },
          stub.streamStatus.status,
        );
        return;
      }
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache, no-transform",
        },
        body: stub.stream,
      });
      return;
    }

    if (request.method() === "GET" && path.endsWith("/messages")) {
      await json(route, stub.messages);
      return;
    }

    if (request.method() === "GET") {
      const chatId = path.replace("/", "");
      const chat = stub.chats.find((item) => item.id === chatId);
      if (!chat) {
        await json(route, { detail: "This chat is no longer available." }, 404);
        return;
      }
      await json(route, { created_at: "2026-08-20T00:00:00Z", ...chat });
      return;
    }

    if (request.method() === "DELETE") {
      const chatId = path.replace("/", "");
      stub.chats = stub.chats.filter((item) => item.id !== chatId);
      await route.fulfill({ status: 204, body: "" });
      return;
    }

    await json(route, {}, 404);
  });

  return stub;
}
