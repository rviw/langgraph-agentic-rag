import { ThemeToggle } from "@/components/ThemeToggle";

export function ChatIndexPage() {
  return (
    <main className="flex min-h-svh flex-col">
      <header className="flex h-14 shrink-0 items-center justify-end border-b px-3">
        <ThemeToggle />
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          LangGraph Agentic RAG
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          Select a chat or start a new one.
        </p>
      </div>
    </main>
  );
}
