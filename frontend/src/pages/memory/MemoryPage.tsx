import { ArrowLeftIcon, OrbitIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useOutletContext } from "react-router";

import type { AuthenticatedOutletContext } from "@/components/auth/RequireAuth";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  deleteAllMemories,
  deleteMemory,
  isAbort,
  isRecoverableApiError,
  listMemories,
  type MemoryResponse,
} from "@/lib/api";

function savedOn(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
    new Date(value),
  );
}

function MemoryManager({ accessToken }: { accessToken: string }) {
  const [memories, setMemories] = useState<MemoryResponse[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [isDeletingAll, setIsDeletingAll] = useState(false);
  const [showDeleteAll, setShowDeleteAll] = useState(false);
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setStatus("loading");
    setLoadError(null);

    try {
      const result = await listMemories(accessToken, current.signal);
      if (!current.signal.aborted) {
        setMemories(result);
        setStatus("ready");
      }
    } catch (cause: unknown) {
      if (current.signal.aborted || isAbort(cause)) {
        return;
      }
      setLoadError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t load saved memories. Try again.",
      );
      setStatus("error");
    } finally {
      if (controller.current === current) {
        controller.current = null;
      }
    }
  }, [accessToken]);

  useEffect(() => {
    const started = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(started);
      controller.current?.abort();
    };
  }, [load]);

  async function handleDelete(memory: MemoryResponse) {
    if (deletingId !== null || isDeletingAll) {
      return;
    }

    setDeletingId(memory.id);
    setActionError(null);
    try {
      await deleteMemory(accessToken, memory.id);
      setMemories((current) => current.filter((item) => item.id !== memory.id));
    } catch (cause: unknown) {
      setActionError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t forget this memory. Try again.",
      );
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDeleteAll() {
    if (deletingId !== null || isDeletingAll) {
      return;
    }

    setIsDeletingAll(true);
    setActionError(null);
    try {
      await deleteAllMemories(accessToken);
      setMemories([]);
      setShowDeleteAll(false);
    } catch (cause: unknown) {
      setActionError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t forget these memories. Try again.",
      );
    } finally {
      setIsDeletingAll(false);
    }
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (showDeleteAll) {
      dialog.showModal();
      cancelRef.current?.focus();
    } else {
      dialog.close();
    }
  }, [showDeleteAll]);

  return (
    <main className="min-h-svh bg-muted/30">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-14 w-full max-w-4xl items-center gap-2 px-4">
          <Button
            asChild
            variant="ghost"
            size="icon"
            aria-label="Back to chats"
            title="Back to chats"
          >
            <Link to="/chats">
              <ArrowLeftIcon aria-hidden="true" />
            </Link>
          </Button>
          <div className="min-w-0 flex-1" />
          <ThemeToggle />
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-4xl gap-6 px-6 py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="grid gap-1">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">
              Memories
            </h1>
            <p className="text-sm text-muted-foreground">
              Details the assistant keeps between chats.
            </p>
          </div>
          <Button
            variant="destructive"
            disabled={
              status !== "ready" ||
              memories.length === 0 ||
              deletingId !== null ||
              isDeletingAll
            }
            onClick={() => setShowDeleteAll(true)}
          >
            <Trash2Icon data-icon="inline-start" aria-hidden="true" />
            Delete all
          </Button>
        </div>

        {actionError && !showDeleteAll && <Alert>{actionError}</Alert>}

        <dialog
          ref={dialogRef}
          role="alertdialog"
          aria-labelledby="delete-memories-title"
          aria-describedby="delete-memories-description"
          className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border-0 bg-card p-5 text-card-foreground shadow-xl ring-1 ring-foreground/10 backdrop:bg-black/50"
          onCancel={(event) => {
            event.preventDefault();
            if (!isDeletingAll) setShowDeleteAll(false);
          }}
          onClose={() => setShowDeleteAll(false)}
        >
          <div className="grid gap-4">
            <div className="grid gap-2">
              <h2
                id="delete-memories-title"
                className="font-heading text-lg font-semibold"
              >
                Delete all saved memories?
              </h2>
              <p
                id="delete-memories-description"
                className="text-sm text-muted-foreground"
              >
                This removes every saved memory from your account and cannot be undone.
              </p>
            </div>
            {actionError && <Alert>{actionError}</Alert>}
            <div className="flex justify-end gap-2">
              <Button
                ref={cancelRef}
                variant="outline"
                disabled={isDeletingAll}
                onClick={() => setShowDeleteAll(false)}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                aria-busy={isDeletingAll}
                disabled={isDeletingAll}
                onClick={() => void handleDeleteAll()}
              >
                {isDeletingAll && (
                  <Spinner data-icon="inline-start" aria-hidden="true" />
                )}
                Delete all memories
              </Button>
            </div>
          </div>
        </dialog>

        <section
          aria-labelledby="saved-memory-list-heading"
          aria-busy={status === "loading"}
          className="rounded-xl border bg-card p-4 sm:p-5"
        >
          <h2 id="saved-memory-list-heading" className="sr-only">
            Saved memory list
          </h2>
          {status === "loading" && (
            <div className="flex min-h-38 items-center justify-center">
              <Spinner aria-label="Loading saved memories" />
            </div>
          )}

          {status === "error" && (
            <div className="grid min-h-38 content-center justify-items-center gap-3 text-center">
              <Alert>{loadError}</Alert>
              <Button variant="outline" size="sm" onClick={() => void load()}>
                Retry
              </Button>
            </div>
          )}

          {status === "ready" && memories.length === 0 && (
            <div className="grid min-h-38 content-center justify-items-center gap-2 text-center">
              <OrbitIcon
                aria-hidden="true"
                className="size-7 text-muted-foreground"
                strokeWidth={1.75}
              />
              <p className="font-medium">No saved memories</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                Helpful details from your chats will appear here.
              </p>
            </div>
          )}

          {memories.length > 0 && (
            <ul aria-label="Saved memories" className="divide-y">
              {memories.map((memory) => (
                <li
                  key={memory.id}
                  data-memory-id={memory.id}
                  className="grid gap-3 py-4 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
                >
                  <div className="grid min-w-0 gap-2">
                    <p className="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">
                      {memory.content}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Saved <time dateTime={memory.created_at}>{savedOn(memory.created_at)}</time>
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete memory: ${memory.content}`}
                    title="Delete memory"
                    aria-busy={deletingId === memory.id}
                    disabled={deletingId !== null || isDeletingAll}
                    className="justify-self-end text-destructive hover:text-destructive"
                    onClick={() => void handleDelete(memory)}
                  >
                    {deletingId === memory.id ? (
                      <Spinner aria-hidden="true" />
                    ) : (
                      <Trash2Icon aria-hidden="true" />
                    )}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}

export function MemoryPage() {
  const { session } = useOutletContext<AuthenticatedOutletContext>();
  // Remount per account so no memories from a previous user remain on screen.
  return (
    <MemoryManager
      key={session.user.id}
      accessToken={session.access_token}
    />
  );
}
