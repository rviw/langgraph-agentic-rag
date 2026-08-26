import { PaperclipIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  confirmDocumentUpload,
  createDocumentUpload,
  deleteDocument,
  getDocument,
  isAbort,
  isRecoverableApiError,
  type DocumentResponse,
} from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

const PDF_MEDIA_TYPE = "application/pdf";
// Statuses that can still change on the server, so the screen keeps polling.
const IN_PROGRESS_STATUSES = new Set(["indexing_pending", "indexing"]);

export type DocumentGate = {
  /** True while a document exists that is not ready to answer questions. */
  blocksSending: boolean;
};

function statusLabel(document: DocumentResponse, isUploading: boolean) {
  switch (document.status) {
    case "upload_pending":
      return isUploading ? "Uploading document…" : "Upload incomplete.";
    case "ready":
      return "Document ready";
    case "indexing_failed":
      return document.indexing_error_code === "invalid_pdf"
        ? "Couldn’t read this document."
        : "Couldn’t process this document.";
    default:
      return "Processing document…";
  }
}

export function ChatDocument({
  accessToken,
  chatId,
  onGateChange,
  children,
}: {
  accessToken: string;
  chatId: string;
  onGateChange: (gate: DocumentGate) => void;
  children: ReactNode;
}) {
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async ({ preserveError = false } = {}) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setStatus("loading");
    if (!preserveError) setError(null);

    try {
      setDocument(await getDocument(accessToken, chatId, current.signal));
      setStatus("ready");
    } catch (cause: unknown) {
      if (current.signal.aborted || isAbort(cause)) {
        return;
      }
      setError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t load document. Try again.",
      );
      setStatus("error");
    } finally {
      if (controller.current === current) {
        controller.current = null;
      }
    }
  }, [accessToken, chatId]);

  useEffect(() => {
    const started = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(started);
      controller.current?.abort();
    };
  }, [load]);

  // While a document is being indexed, its status changes on the server only.
  const documentStatus = document?.status;
  useEffect(() => {
    if (status !== "ready" || !documentStatus || !IN_PROGRESS_STATUSES.has(documentStatus)) {
      return;
    }

    const polling = new AbortController();
    const interval = window.setInterval(() => {
      void getDocument(accessToken, chatId, polling.signal)
        .then((next) => {
          if (!polling.signal.aborted) {
            setDocument(next);
          }
        })
        .catch(() => {
          // A missed poll is retried by the next tick.
        });
    }, 1000);

    return () => {
      window.clearInterval(interval);
      polling.abort();
    };
  }, [accessToken, chatId, documentStatus, status]);

  const blocksSending =
    status !== "ready" || isUploading || (document !== null && document.status !== "ready");
  useEffect(() => {
    onGateChange({ blocksSending });
  }, [blocksSending, onGateChange]);

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file || status !== "ready" || document !== null || isUploading) {
      return;
    }

    setIsUploading(true);
    setError(null);
    try {
      const reservation = await createDocumentUpload(accessToken, chatId, {
        original_filename: file.name,
        media_type: file.type || PDF_MEDIA_TYPE,
        size_bytes: file.size,
      });
      setDocument(reservation.document);

      const { error: uploadError } = await supabase.storage
        .from(reservation.upload.bucket)
        .uploadToSignedUrl(
          reservation.upload.path,
          reservation.upload.token,
          file,
          { contentType: PDF_MEDIA_TYPE },
        );
      if (uploadError) {
        throw uploadError;
      }

      setDocument(await confirmDocumentUpload(accessToken, chatId));
    } catch (cause: unknown) {
      setError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t upload this document. Try again.",
      );
      // Show whatever the server actually holds after a partial upload.
      await load({ preserveError: true });
    } finally {
      setIsUploading(false);
    }
  }

  async function handleRemove() {
    if (document === null || isRemoving || isUploading) {
      return;
    }

    setIsRemoving(true);
    setError(null);
    try {
      await deleteDocument(accessToken, chatId);
      setDocument(null);
    } catch (cause: unknown) {
      setError(
        isRecoverableApiError(cause)
          ? cause.message
          : "Couldn’t remove this document. Try again.",
      );
    } finally {
      setIsRemoving(false);
    }
  }

  const hasFailed =
    document !== null &&
    (document.status === "indexing_failed" ||
      (document.status === "upload_pending" && !isUploading));
  const canRemove = document !== null && document.status !== "indexing" && document.status !== "ready";

  return (
    <>
      {(error || document !== null) && (
        <div className="w-full px-3 pt-2 text-xs">
          <div className="mx-auto w-full max-w-3xl">
            {error && (
              <div className="flex min-h-11 items-center gap-2">
                <Alert className="text-xs">{error}</Alert>
                {status === "error" && (
                  <Button variant="ghost" size="xs" onClick={() => void load()}>
                    Retry
                  </Button>
                )}
              </div>
            )}

            {document !== null && (
              <ul aria-label="Document" className="flex flex-col gap-1">
                <li className={cn(
                  "grid h-11 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 rounded-md bg-muted px-2.5",
                  canRemove && !isUploading && "grid-cols-[minmax(0,1fr)_minmax(0,auto)_auto]",
                )}>
                  <span title={document.original_filename} className="min-w-0 truncate font-medium">
                    {document.original_filename}
                  </span>
                  <span
                    aria-live="polite"
                    className={cn(
                      "flex min-w-0 items-center gap-1.5 whitespace-nowrap",
                      hasFailed
                        ? "justify-self-end overflow-hidden text-destructive"
                        : document.status === "ready"
                          ? "shrink-0 justify-self-end text-emerald-700 dark:text-emerald-400"
                          : "shrink-0 justify-self-end text-blue-700 dark:text-blue-300",
                    )}
                  >
                    {isUploading || document.status === "indexing" ? (
                      <Spinner aria-hidden="true" />
                    ) : (
                      <span
                        aria-hidden="true"
                        className={cn(
                          "size-1.5 shrink-0 rounded-full bg-current",
                          document.status !== "ready" && !hasFailed && "animate-pulse",
                        )}
                      />
                    )}
                    <span className={cn(hasFailed && "truncate")}>
                      {statusLabel(document, isUploading)}
                    </span>
                  </span>
                  {canRemove && !isUploading && (
                    <Button
                      variant="ghost"
                      size="xs"
                      aria-label={`Remove ${document.original_filename}`}
                      aria-busy={isRemoving}
                      disabled={isRemoving}
                      className="w-14 justify-self-end text-destructive hover:text-destructive"
                      onClick={() => void handleRemove()}
                    >
                      Remove
                    </Button>
                  )}
                </li>
              </ul>
            )}
          </div>
        </div>
      )}

      <div className="grid gap-2 p-3">
        <div className="relative mx-auto w-full max-w-3xl overflow-hidden rounded-xl border bg-transparent shadow-xs focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
          {document === null && (
            <>
              <input
                ref={fileInput}
                type="file"
                name="document"
                accept="application/pdf,.pdf"
                className="hidden"
                onChange={(event) => void handleUpload(event)}
              />
              <Button
                variant="ghost"
                size="icon"
                aria-label="Attach PDF"
                aria-busy={isUploading}
                disabled={status !== "ready" || isUploading}
                className="absolute bottom-2 left-2"
                onClick={() => fileInput.current?.click()}
              >
                {isUploading ? (
                  <Spinner aria-hidden="true" />
                ) : (
                  <PaperclipIcon aria-hidden="true" className="size-4" />
                )}
              </Button>
            </>
          )}
          {children}
        </div>
      </div>
    </>
  );
}
