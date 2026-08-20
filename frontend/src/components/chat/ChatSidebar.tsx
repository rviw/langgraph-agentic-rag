import {
  CircleUserRoundIcon,
  LogOutIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { isRecoverableApiError, type ChatResponse } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

type ChatSidebarProps = {
  email: string;
  chats: ChatResponse[];
  isLoading: boolean;
  isCreating: boolean;
  listError: string | null;
  createError: string | null;
  onCreateChat: () => void;
  onDeleteChat: (chat: ChatResponse) => Promise<void>;
  onRetry: () => void;
};

export function ChatSidebar({
  email,
  chats,
  isLoading,
  isCreating,
  listError,
  createError,
  onCreateChat,
  onDeleteChat,
  onRetry,
}: ChatSidebarProps) {
  const [deleteTarget, setDeleteTarget] = useState<ChatResponse | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (deleteTarget) {
      dialog.showModal();
      cancelRef.current?.focus();
    } else {
      dialog.close();
    }
  }, [deleteTarget]);

  async function handleDelete() {
    if (!deleteTarget || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await onDeleteChat(deleteTarget);
      setDeleteTarget(null);
    } catch (cause: unknown) {
      setDeleteError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t delete this chat. Try again.",
      );
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <span className="min-w-0 flex-1 truncate px-1 font-semibold">Chats</span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="New chat"
          aria-busy={isCreating}
          disabled={isLoading || isCreating}
          onClick={onCreateChat}
        >
          {isCreating ? (
            <Spinner aria-hidden="true" />
          ) : (
            <PlusIcon aria-hidden="true" className="size-4" />
          )}
        </Button>
        <div className="md:hidden">
          <ThemeToggle />
        </div>
      </header>

      <nav
        aria-label="Chats"
        className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-3"
      >
        {isLoading && chats.length === 0 && (
          <div className="flex flex-1 items-center justify-center py-12">
            <Spinner aria-label="Loading chats" />
          </div>
        )}

        {listError && !isLoading && (
          <div
            className={cn(
              "grid justify-items-center gap-3 px-3 py-2 text-center",
              chats.length === 0 && "flex-1 place-content-center py-12",
            )}
          >
            <Alert>{listError}</Alert>
            <Button variant="outline" size="sm" className="w-fit" onClick={onRetry}>
              Retry
            </Button>
          </div>
        )}

        {!isLoading && !listError && chats.length === 0 && (
          <p className="px-3 py-2 text-sm text-muted-foreground">
            No chats yet. Start a new one.
          </p>
        )}

        {createError && <Alert className="px-3 py-2">{createError}</Alert>}

        <ul className="grid shrink-0 gap-1">
          {chats.map((chat) => (
            <li key={chat.id} className="group relative">
              <NavLink
                to={`/chats/${chat.id}`}
                className={({ isActive }) =>
                  cn(
                    "block min-h-11 truncate rounded-md py-3 pr-12 pl-3 text-sm md:min-h-0 md:py-2 md:pr-10",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                  )
                }
              >
                {chat.title}
              </NavLink>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Delete ${chat.title}`}
                aria-haspopup="dialog"
                aria-busy={isDeleting && deleteTarget?.id === chat.id}
                disabled={isDeleting}
                className="absolute top-1/2 right-0 size-11 -translate-y-1/2 text-muted-foreground hover:text-destructive md:right-1 md:size-8 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100"
                onClick={() => {
                  setDeleteError(null);
                  setDeleteTarget(chat);
                }}
              >
                {isDeleting && deleteTarget?.id === chat.id ? (
                  <Spinner aria-hidden="true" />
                ) : (
                  <Trash2Icon aria-hidden="true" className="size-4" />
                )}
              </Button>
            </li>
          ))}
        </ul>
      </nav>

      <footer className="flex shrink-0 items-center border-t px-5 py-3">
        <CircleUserRoundIcon
          aria-hidden="true"
          className="mr-1.5 size-[15px] shrink-0 text-muted-foreground"
          strokeWidth={1.75}
        />
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {email}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 gap-2 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => void supabase.auth.signOut({ scope: "local" })}
        >
          <LogOutIcon
            aria-hidden="true"
            data-icon="inline-start"
            className="size-[15px]"
          />
          Sign out
        </Button>
      </footer>

      <dialog
        ref={dialogRef}
        role="alertdialog"
        aria-labelledby="delete-chat-title"
        aria-describedby="delete-chat-description"
        className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-md rounded-xl bg-card p-5 text-card-foreground shadow-xl ring-1 ring-foreground/10 backdrop:bg-black/50"
        onCancel={(event) => {
          event.preventDefault();
          if (!isDeleting) setDeleteTarget(null);
        }}
        onClose={() => setDeleteTarget(null)}
      >
        <div className="grid gap-4">
          <div className="grid gap-2">
            <h2 id="delete-chat-title" className="font-heading text-lg font-semibold">
              Delete chat?
            </h2>
            <p
              id="delete-chat-description"
              className="text-sm text-muted-foreground [overflow-wrap:anywhere]"
            >
              “{deleteTarget?.title}” and its messages will be permanently deleted.
              This action cannot be undone.
            </p>
            {deleteError && <Alert>{deleteError}</Alert>}
          </div>
          <div className="flex justify-end gap-2">
            <Button
              ref={cancelRef}
              variant="outline"
              disabled={isDeleting}
              onClick={() => setDeleteTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              aria-busy={isDeleting}
              disabled={isDeleting}
              onClick={() => void handleDelete()}
            >
              {isDeleting && <Spinner aria-hidden="true" />}
              Delete
            </Button>
          </div>
        </div>
      </dialog>
    </div>
  );
}
