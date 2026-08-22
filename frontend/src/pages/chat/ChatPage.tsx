import { ArrowUpIcon, CircleAlertIcon, RotateCcwIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useOutletContext, useParams } from "react-router";

import type { ChatOutletContext } from "@/components/chat/ChatLayout";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  isAbort,
  isRecoverableApiError,
  listChatMessages,
  streamChatMessage,
  type ChatMessageResponse,
  type ExecutionPhase,
} from "@/lib/api";

const PHASE_LABELS: Record<ExecutionPhase, string> = {
  understanding: "Understanding your request…",
  searching: "Searching sources…",
  reading: "Reading sources…",
  validating: "Checking sources…",
  writing: "Writing response…",
};

function withMessage(
  messages: ChatMessageResponse[],
  message: ChatMessageResponse,
) {
  const index = messages.findIndex((item) => item.id === message.id);
  if (index < 0) {
    return [...messages, message];
  }
  const next = [...messages];
  next[index] = message;
  return next;
}

function ChatView({
  chatId,
  accessToken,
  refreshChats,
}: {
  chatId: string;
  accessToken: string;
  refreshChats: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessageResponse[]>([]);
  const [historyStatus, setHistoryStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [phase, setPhase] = useState<ExecutionPhase | null>(null);
  const [input, setInput] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [failedContent, setFailedContent] = useState<string | null>(null);
  const historyController = useRef<AbortController | null>(null);
  const streamController = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const loadMessages = useCallback(async () => {
    historyController.current?.abort();
    const controller = new AbortController();
    historyController.current = controller;
    setHistoryStatus("loading");
    setHistoryError(null);

    try {
      const stored = await listChatMessages(
        accessToken,
        chatId,
        controller.signal,
      );
      setMessages(stored);
      setHistoryStatus("ready");
    } catch (cause: unknown) {
      if (controller.signal.aborted || isAbort(cause)) {
        return;
      }
      setHistoryError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t load messages. Try again.",
      );
      setHistoryStatus("error");
    } finally {
      if (historyController.current === controller) {
        historyController.current = null;
      }
    }
  }, [accessToken, chatId]);

  useEffect(() => {
    const started = window.setTimeout(() => void loadMessages(), 0);
    return () => {
      window.clearTimeout(started);
      historyController.current?.abort();
      streamController.current?.abort();
    };
  }, [loadMessages]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [isSending, messages]);

  async function sendMessage(content: string, { fromInput }: { fromInput: boolean }) {
    const controller = new AbortController();
    streamController.current = controller;
    setIsSending(true);
    setPhase(null);
    setSendError(null);
    setFailedContent(null);
    let completed = false;

    try {
      for await (const event of streamChatMessage(
        accessToken,
        chatId,
        content,
        controller.signal,
      )) {
        if (event.type === "execution.progress") {
          setPhase(event.phase);
          continue;
        }
        setMessages((current) => withMessage(current, event.message));
        if (event.type === "message.accepted") {
          setInput((current) => (current === content ? "" : current));
        } else {
          completed = true;
          setPhase(null);
          // The first answer names the chat, so the sidebar needs a refresh.
          void refreshChats();
        }
      }
    } catch (cause: unknown) {
      if (controller.signal.aborted || isAbort(cause)) {
        return;
      }
      if (!completed) {
        // Give the text back so the request can be retried without retyping.
        if (fromInput) {
          setInput((current) => (current.length > 0 ? current : content));
        }
        setFailedContent(content);
      }
      setSendError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t generate a response.",
      );
    } finally {
      if (streamController.current === controller) {
        streamController.current = null;
        setIsSending(false);
        setPhase(null);
      }
    }
  }

  const isReady = historyStatus === "ready";
  const canSend = isReady && !isSending;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = input.trim();
    if (!content || !canSend) {
      return;
    }
    await sendMessage(content, { fromInput: true });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div
        role="log"
        aria-label="Messages"
        aria-busy={historyStatus === "loading" || isSending}
        className="min-h-0 flex-1 overscroll-contain overflow-x-hidden overflow-y-auto px-4 py-6"
      >
        <div className="mx-auto flex min-w-0 w-full max-w-3xl flex-col gap-4">
          {historyStatus === "loading" && (
            <div className="flex justify-center py-12">
              <Spinner aria-label="Loading messages" />
            </div>
          )}

          {historyStatus === "error" && (
            <div className="flex flex-col items-center gap-3 py-12">
              <Alert>{historyError}</Alert>
              <Button variant="outline" size="sm" onClick={() => void loadMessages()}>
                Retry
              </Button>
            </div>
          )}

          {isReady && messages.length === 0 && !isSending && (
            <p className="py-12 text-center text-sm text-muted-foreground">
              Send a message to start the chat.
            </p>
          )}

          {messages.map((message) => (
            <article
              key={message.id}
              data-message-id={message.id}
              aria-label={message.role === "user" ? "You" : "Assistant"}
              className={
                message.role === "user"
                  ? "ml-auto min-w-0 w-fit max-w-[78%] rounded-2xl bg-primary px-4 py-3 text-sm whitespace-pre-wrap break-words text-primary-foreground [overflow-wrap:anywhere] sm:max-w-[75%]"
                  : "mr-auto min-w-0 w-fit max-w-[78%] rounded-2xl bg-muted px-4 py-3 text-sm whitespace-pre-wrap text-foreground [overflow-wrap:anywhere]"
              }
            >
              {message.content}
            </article>
          ))}

          {isSending && (
            <div
              role="status"
              className="mr-auto flex items-center gap-2 rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground"
            >
              <Spinner aria-hidden="true" />
              {phase === null ? "Generating response…" : PHASE_LABELS[phase]}
            </div>
          )}

          {sendError && !isSending && (
            <div role="alert" className="mr-auto flex w-fit max-w-full items-center gap-2 rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive">
              <CircleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{sendError}</span>
              {failedContent !== null && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="shrink-0 text-destructive hover:text-destructive"
                  onClick={() => void sendMessage(failedContent, { fromInput: false })}
                >
                  <RotateCcwIcon data-icon="inline-start" aria-hidden="true" />
                  Retry
                </Button>
              )}
            </div>
          )}

          <div
            ref={endRef}
            aria-hidden="true"
          />
        </div>
      </div>

      <form className="shrink-0 border-t bg-background p-3" onSubmit={handleSubmit}>
        <div className="relative mx-auto w-full max-w-3xl overflow-hidden rounded-xl border bg-transparent shadow-xs focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
          <textarea
            aria-label="Message"
            name="message"
            rows={3}
            maxLength={4000}
            value={input}
            disabled={!isReady}
            placeholder="Type a message…"
            className="block min-h-22 w-full resize-none bg-transparent px-3 pt-3 pb-12 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <Button
            type="submit"
            size="icon"
            aria-label="Send message"
            aria-busy={isSending}
            disabled={!canSend || !input.trim()}
            className="absolute right-2 bottom-2"
          >
            {isSending ? <Spinner aria-hidden="true" /> : <ArrowUpIcon aria-hidden="true" />}
          </Button>
        </div>
      </form>
    </section>
  );
}

export function ChatPage() {
  // The ":chatId" route always supplies this parameter.
  const { chatId } = useParams() as { chatId: string };
  const { accessToken, refreshChats } = useOutletContext<ChatOutletContext>();
  // Remount per chat so no messages or in-flight state cross between chats.
  return (
    <ChatView
      key={chatId}
      chatId={chatId}
      accessToken={accessToken}
      refreshChats={refreshChats}
    />
  );
}
