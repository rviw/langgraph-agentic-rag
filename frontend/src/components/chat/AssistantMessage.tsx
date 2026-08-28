import { ExternalLinkIcon, FileTextIcon, GlobeIcon, XIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type ComponentProps, type ReactNode } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  getSourceDetail,
  isAbort,
  isRecoverableApiError,
  type CitationResponse,
  type SourceDetailResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const PROSE =
  "min-w-0 break-words [overflow-wrap:anywhere] [&_blockquote]:my-3 [&_blockquote]:max-w-full [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:font-mono [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:max-w-full [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:max-w-full [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:max-w-full [&_h3]:font-semibold [&_hr]:my-4 [&_li]:my-1 [&_li]:max-w-full [&_ol]:my-3 [&_ol]:max-w-full [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_p]:max-w-full [&_p]:whitespace-normal [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:bg-background [&_pre]:px-3 [&_pre]:py-4 [&_pre]:text-xs [&_pre]:leading-relaxed [&_strong]:break-words [&_table]:my-3 [&_table]:w-full [&_table]:table-fixed [&_table]:border-collapse [&_td]:break-words [&_td]:border [&_td]:p-2 [&_th]:break-words [&_th]:border [&_th]:bg-background [&_th]:p-2 [&_th]:text-left [&_ul]:my-3 [&_ul]:max-w-full [&_ul]:list-disc [&_ul]:pl-5 [&_:not(pre)>code]:break-all [&_:not(pre)>code]:rounded [&_:not(pre)>code]:bg-background [&_:not(pre)>code]:px-1 [&_:not(pre)>code]:py-0.5";

// Answer Markdown comes from a model, so only these elements may render.
const ALLOWED_ELEMENTS = [
  "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5",
  "h6", "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th",
  "thead", "tr", "ul",
] as const;

const CITATION_HREF = /^#answer-source-(\d+)$/u;

/** Allow only links a reader can safely follow. */
function safeUrl(value: string): string | null {
  if (value.trim() !== value) {
    return null;
  }
  if (Array.from(value).some((character) => {
    const code = character.codePointAt(0) ?? 0;
    return code <= 31 || code === 127;
  })) return null;
  try {
    const url = new URL(value);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.hostname ? value : null;
    }
    if (url.protocol === "mailto:") {
      return url.pathname ? value : null;
    }
  } catch {
    return null;
  }
  return null;
}

function citationOrdinal(href: string | undefined): number | null {
  const match = href?.match(CITATION_HREF);
  return match ? Number(match[1]) : null;
}

function SafeLink({ children, href, ...props }: ComponentProps<"a"> & ExtraProps) {
  const target = typeof href === "string" ? safeUrl(href) : null;
  if (!target) {
    return <span>{children}</span>;
  }
  const isExternal = !target.startsWith("mailto:");
  return (
    <a
      {...props}
      href={target}
      className="font-medium underline underline-offset-2 hover:no-underline"
      target={isExternal ? "_blank" : undefined}
      rel={isExternal ? "noopener noreferrer" : undefined}
    >
      {children}
    </a>
  );
}

type MarkdownNode = {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
};

/** Turn in-range [n] markers into links the reader can open. */
function remarkCitations(citationCount: number) {
  return () => (tree: MarkdownNode) => {
    const visit = (node: MarkdownNode) => {
      if (!node.children || node.type === "link" || node.type === "inlineCode") {
        return;
      }
      node.children = node.children.flatMap((child) => {
        if (child.type !== "text" || !child.value) {
          visit(child);
          return [child];
        }
        const parts: MarkdownNode[] = [];
        let cursor = 0;
        for (const match of child.value.matchAll(/\[(\d+)\]/gu)) {
          const ordinal = Number(match[1]);
          if (ordinal < 1 || ordinal > citationCount) {
            continue;
          }
          if (match.index > cursor) {
            parts.push({
              type: "text",
              value: child.value.slice(cursor, match.index),
            });
          }
          parts.push({
            type: "link",
            url: `#answer-source-${ordinal}`,
            children: [{ type: "text", value: match[0] }],
          });
          cursor = match.index + match[0].length;
        }
        if (parts.length === 0) {
          return [child];
        }
        if (cursor < child.value.length) {
          parts.push({ type: "text", value: child.value.slice(cursor) });
        }
        return parts;
      });
    };
    visit(tree);
  };
}

function DocumentSourceView({
  detail,
}: {
  detail: Extract<SourceDetailResponse, { type: "document" }>;
}) {
  const passages = [
    ...detail.context.map((item) => ({ ...item, cited: false })),
    {
      chunk_id: detail.chunk_id,
      chunk_index: detail.chunk_index,
      page: detail.page,
      excerpt: detail.excerpt,
      cited: true,
    },
  ].sort((left, right) => left.chunk_index - right.chunk_index);

  return (
    <div className="grid min-w-0 max-w-full gap-4">
      <div className="flex min-w-0 max-w-full items-start gap-2">
        <FileTextIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 max-w-full flex-1">
          <p className="font-medium [overflow-wrap:anywhere]">{detail.filename}</p>
          <p className="text-xs text-muted-foreground">
            Passages from this document
          </p>
        </div>
      </div>
      <ol aria-label="Document passages" className="grid min-w-0 max-w-full gap-3">
        {passages.map((passage) => (
          <li
            key={passage.chunk_id}
            className={cn(
              "grid min-w-0 max-w-full gap-1 rounded-lg border p-3",
              passage.cited && "border-foreground/30 bg-muted",
            )}
          >
            <p className="text-xs font-medium text-muted-foreground">
              Page {passage.page}
              {passage.cited ? " · Cited passage" : " · Adjacent context"}
            </p>
            <p className="min-w-0 max-w-full text-sm whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {passage.excerpt}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}

function WebSourceView({
  detail,
}: {
  detail: Extract<SourceDetailResponse, { type: "web" }>;
}) {
  const target = safeUrl(detail.url);
  return (
    <div className="grid min-w-0 max-w-full gap-4">
      <div className="flex min-w-0 max-w-full items-start gap-2">
        <GlobeIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <p className="min-w-0 max-w-full break-words font-medium [overflow-wrap:anywhere]">
          {detail.title}
        </p>
      </div>
      <p className="min-w-0 max-w-full text-sm whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {detail.excerpt}
      </p>
      {target && (
        <a
          href={target}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex w-fit items-center gap-1 text-sm font-medium underline underline-offset-2 hover:no-underline"
        >
          Open original source
          <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
        </a>
      )}
    </div>
  );
}

function SourceDrawer({
  accessToken,
  chatId,
  messageId,
  citation,
  ordinal,
  onClose,
}: {
  accessToken: string;
  chatId: string;
  messageId: string;
  citation: CitationResponse;
  ordinal: number;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    closeRef.current?.focus();
    return () => dialog?.close();
  }, []);

  const [detail, setDetail] = useState<SourceDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    void getSourceDetail(
      accessToken,
      chatId,
      messageId,
      citation.source_id,
      controller.signal,
    )
      .then((next) => {
        if (!controller.signal.aborted) {
          setDetail(next);
        }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || isAbort(cause)) {
          return;
        }
        setError(
          isRecoverableApiError(cause)
            ? cause.message
            : "Couldn’t load this source. Try again.",
        );
      });

    return () => controller.abort();
  }, [accessToken, chatId, citation.source_id, messageId, attempt]);

  let body: ReactNode;
  if (error !== null) {
    body = (
      <div className="grid gap-3">
        <Alert>{error}</Alert>
        <Button variant="outline" size="sm" className="w-fit" onClick={() => {
          setError(null);
          setDetail(null);
          setAttempt((current) => current + 1);
        }}>Retry</Button>
      </div>
    );
  } else if (detail === null) {
    body = (
      <div
        role="status"
        className="flex items-center gap-2 text-sm text-muted-foreground"
      >
        <Spinner aria-hidden="true" />
        Loading source details…
      </div>
    );
  } else if (detail.type === "document") {
    body = <DocumentSourceView detail={detail} />;
  } else {
    body = <WebSourceView detail={detail} />;
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none w-full max-w-md min-w-0 overflow-x-hidden overflow-y-auto border-l bg-background p-5 text-foreground shadow-xl backdrop:bg-black/40"
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}
    >
      <div className="flex min-w-0 flex-col gap-5">
        <div className="grid min-w-0 max-w-full gap-1 pr-10">
          <h2 id={titleId} className="font-heading text-lg font-semibold">Source [{ordinal}]</h2>
          <p id={descriptionId} className="text-sm text-muted-foreground">
            {citation.type === "document"
              ? "Document passage used for this answer"
              : "Web result used for this answer"}
          </p>
          <Button ref={closeRef} variant="ghost" size="icon-sm" aria-label="Close source details" className="absolute top-4 right-4" onClick={onClose}>
            <XIcon aria-hidden="true" />
          </Button>
        </div>
        {body}
      </div>
    </dialog>
  );
}

export function AssistantMessage({
  accessToken,
  chatId,
  messageId,
  content,
  citations,
}: {
  accessToken: string;
  chatId: string;
  messageId: string;
  content: string;
  citations: CitationResponse[];
}) {
  const articleRef = useRef<HTMLElement | null>(null);
  const [openOrdinal, setOpenOrdinal] = useState<number | null>(null);
  const selected =
    openOrdinal === null ? null : (citations[openOrdinal - 1] ?? null);

  const components: Components = {
    a: ({ children, href, ...props }) => {
      const ordinal = citationOrdinal(href);
      if (ordinal === null) {
        return (
          <SafeLink {...props} href={href}>
            {children}
          </SafeLink>
        );
      }
      return (
        <button
          type="button"
          aria-label={`View source ${ordinal}`}
          data-source-ordinal={ordinal}
          className="inline cursor-pointer font-medium underline underline-offset-2 hover:no-underline"
          onClick={() => setOpenOrdinal(ordinal)}
        >
          {children}
        </button>
      );
    },
  };

  return (
    <>
      <article
        ref={articleRef}
        aria-label="Assistant"
        data-message-id={messageId}
        className={cn("mr-auto w-fit max-w-[78%] rounded-2xl bg-muted px-4 py-3 text-sm text-foreground sm:max-w-[75%]", PROSE)}
      >
          <ReactMarkdown
            allowedElements={[...ALLOWED_ELEMENTS]}
            components={components}
            rehypePlugins={[rehypeSanitize]}
            remarkPlugins={[remarkGfm, remarkCitations(citations.length)]}
            skipHtml
            urlTransform={(url) =>
              citationOrdinal(url) === null ? safeUrl(url) : url
            }
          >
            {content}
          </ReactMarkdown>
      </article>

      {selected !== null && openOrdinal !== null && (
        <SourceDrawer
          key={`${messageId}:${selected.source_id}`}
          accessToken={accessToken}
          chatId={chatId}
          messageId={messageId}
          citation={selected}
          ordinal={openOrdinal}
          onClose={() => {
            setOpenOrdinal(null);
            // Markdown renderers are recreated on state changes, so focus the
            // current citation button after the closed state has rendered.
            requestAnimationFrame(() => {
              articleRef.current
                ?.querySelector<HTMLButtonElement>(`[data-source-ordinal="${openOrdinal}"]`)
                ?.focus();
            });
          }}
        />
      )}
    </>
  );
}
