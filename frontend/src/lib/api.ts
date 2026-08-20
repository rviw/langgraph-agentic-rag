const API_BASE_URL = "/api";

const CHATS_URL = `${API_BASE_URL}/chats`;

export type ChatResponse = {
  id: string;
  title: string;
  created_at: string;
};

export type ChatMessageResponse = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type ExecutionPhase =
  | "understanding"
  | "searching"
  | "reading"
  | "writing"
  | "validating";

export type ChatMessageEvent =
  | { type: "message.accepted"; message: ChatMessageResponse }
  | { type: "execution.progress"; phase: ExecutionPhase }
  | { type: "message.completed"; message: ChatMessageResponse };

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** True when a failure is worth showing verbatim instead of a generic message. */
export function isRecoverableApiError(cause: unknown): cause is ApiError {
  return cause instanceof ApiError && cause.status >= 400 && cause.status < 500;
}

export function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

function authorized(accessToken: string, init: RequestInit = {}): RequestInit {
  return {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${accessToken}`,
    },
  };
}

async function request(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (cause: unknown) {
    if (isAbort(cause)) {
      throw cause;
    }
    // A transport failure has no status, so callers cannot mistake it for a 4xx.
    throw new ApiError(0, "Couldn’t connect. Try again.");
  }
}

async function failure(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // Proxy and framework errors are not always JSON.
  }
  return new ApiError(
    response.status,
    typeof detail === "string" ? detail : "Something went wrong. Try again.",
  );
}

async function parsed<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as T;
}

async function expectNoContent(response: Response): Promise<void> {
  if (!response.ok) {
    throw await failure(response);
  }
}

export async function listChats(
  accessToken: string,
  signal?: AbortSignal,
): Promise<ChatResponse[]> {
  return parsed(await request(CHATS_URL, authorized(accessToken, { signal })));
}

export async function getChat(
  accessToken: string,
  chatId: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return parsed(
    await request(
      `${CHATS_URL}/${encodeURIComponent(chatId)}`,
      authorized(accessToken, { signal }),
    ),
  );
}

export async function createChat(
  accessToken: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return parsed(
    await request(CHATS_URL, authorized(accessToken, { method: "POST", signal })),
  );
}

export async function deleteChat(
  accessToken: string,
  chatId: string,
): Promise<void> {
  await expectNoContent(
    await request(
      `${CHATS_URL}/${encodeURIComponent(chatId)}`,
      authorized(accessToken, { method: "DELETE" }),
    ),
  );
}

function messagesUrl(chatId: string): string {
  return `${CHATS_URL}/${encodeURIComponent(chatId)}/messages`;
}

export async function listChatMessages(
  accessToken: string,
  chatId: string,
  signal?: AbortSignal,
): Promise<ChatMessageResponse[]> {
  return parsed(
    await request(messagesUrl(chatId), authorized(accessToken, { signal })),
  );
}

/** Read one SSE block, raising the server's failure event as an error. */
function parseEvent(block: string): ChatMessageEvent | null {
  let name: string | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      name = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice("data:".length).trimStart());
    }
  }
  if (name === null || data.length === 0) {
    return null;
  }

  const payload = JSON.parse(data.join("\n")) as Record<string, unknown>;
  if (name === "execution.failed") {
    const error = payload.error as { message: string };
    throw new ApiError(0, error.message);
  }
  if (name === "execution.progress") {
    return { type: name, phase: payload.phase as ExecutionPhase };
  }
  if (name === "message.accepted" || name === "message.completed") {
    return {
      type: name,
      message: payload.message as ChatMessageResponse,
    };
  }
  return null;
}

async function* readEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ChatMessageEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (cause: unknown) {
        if (isAbort(cause)) {
          throw cause;
        }
        throw new ApiError(0, "Couldn’t connect. Try again.");
      }

      buffer += chunk.done
        ? decoder.decode()
        : decoder.decode(chunk.value, { stream: true });
      buffer = buffer.replaceAll("\r\n", "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const event = parseEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (event) {
          yield event;
        }
        boundary = buffer.indexOf("\n\n");
      }

      if (chunk.done) {
        const event = parseEvent(buffer);
        if (event) {
          yield event;
        }
        return;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* streamChatMessage(
  accessToken: string,
  chatId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatMessageEvent> {
  const response = await request(
    messagesUrl(chatId),
    authorized(accessToken, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content }),
      signal,
    }),
  );
  if (!response.ok) {
    throw await failure(response);
  }
  yield* readEvents(response.body!);
}
