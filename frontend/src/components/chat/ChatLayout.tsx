import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useMatch, useNavigate, useOutletContext } from "react-router";

import type { AuthenticatedOutletContext } from "@/components/auth/RequireAuth";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import {
  ApiError,
  createChat,
  deleteChat,
  isAbort,
  isRecoverableApiError,
  listChats,
  type ChatResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export type ChatOutletContext = {
  accessToken: string;
  refreshChats: () => Promise<void>;
};

export function ChatLayout() {
  const { session } = useOutletContext<AuthenticatedOutletContext>();
  // Remount on account change so no state from a previous user survives.
  return (
    <AuthenticatedChatLayout
      key={session.user.id}
      accessToken={session.access_token}
      email={session.user.email ?? ""}
    />
  );
}

function AuthenticatedChatLayout({
  accessToken,
  email,
}: {
  accessToken: string;
  email: string;
}) {
  const navigate = useNavigate();
  const chatId = useMatch("/chats/:chatId")?.params.chatId;
  const [chats, setChats] = useState<ChatResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const listController = useRef<AbortController | null>(null);

  const loadChats = useCallback(async () => {
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;

    try {
      const items = await listChats(accessToken, controller.signal);
      if (!controller.signal.aborted) {
        setChats(items);
        setListError(null);
      }
    } catch (cause: unknown) {
      if (controller.signal.aborted || isAbort(cause)) {
        return;
      }
      // Keep any chats already on screen rather than emptying the sidebar.
      setListError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t load chats. Try again.",
      );
    } finally {
      if (listController.current === controller) {
        listController.current = null;
      }
      if (!controller.signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [accessToken]);

  useEffect(() => {
    const started = window.setTimeout(() => void loadChats(), 0);
    return () => {
      window.clearTimeout(started);
      listController.current?.abort();
    };
  }, [loadChats]);

  const retryChats = useCallback(async () => {
    setIsLoading(true);
    setListError(null);
    await loadChats();
  }, [loadChats]);

  async function handleCreateChat() {
    if (isCreating || isLoading) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      const chat = await createChat(accessToken);
      setChats((current) => [chat, ...current]);
      void navigate(`/chats/${chat.id}`);
    } catch (cause: unknown) {
      setCreateError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t create a chat. Try again.",
      );
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDeleteChat(chat: ChatResponse) {
    try {
      await deleteChat(accessToken, chat.id);
    } catch (cause: unknown) {
      // A chat that is already gone is the outcome the caller asked for.
      if (!(cause instanceof ApiError && cause.status === 404)) {
        throw cause;
      }
    }

    setChats((current) => current.filter((item) => item.id !== chat.id));
    if (chatId === chat.id) {
      void navigate("/chats", { replace: true });
    }
  }

  const selectedChat = chats.find((chat) => chat.id === chatId);

  return (
    <main
      className={cn(
        "fixed inset-0 grid min-h-0 w-full grid-cols-[minmax(0,1fr)] overflow-hidden",
        isSidebarOpen && "md:grid-cols-[20rem_minmax(0,1fr)]",
      )}
    >
      <div
        id="chat-sidebar"
        className={cn(
          "min-h-0 min-w-0 flex-col border-r bg-sidebar text-sidebar-foreground",
          chatId ? "hidden md:flex" : "flex",
          !isSidebarOpen && "md:hidden",
        )}
      >
        <ChatSidebar
          email={email}
          chats={chats}
          isLoading={isLoading}
          isCreating={isCreating}
          listError={listError}
          createError={createError}
          onCreateChat={() => void handleCreateChat()}
          onDeleteChat={handleDeleteChat}
          onRetry={() => void retryChats()}
        />
      </div>

      <div
        className={cn(
          "flex min-h-0 min-w-0 flex-col bg-background",
          chatId ? "flex" : "hidden md:flex",
        )}
      >
        <ChatHeader
          chatId={chatId}
          title={selectedChat?.title}
          isSidebarOpen={isSidebarOpen}
          onToggleSidebar={() => setIsSidebarOpen((open) => !open)}
        />

        <div className="min-h-0 min-w-0 flex-1">
          <Outlet
            context={
              {
                accessToken,
                refreshChats: loadChats,
              } satisfies ChatOutletContext
            }
          />
        </div>
      </div>
    </main>
  );
}
