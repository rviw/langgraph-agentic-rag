export function ChatIndexPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">
        LangGraph Agentic RAG
      </h1>
      <p className="max-w-md text-sm text-muted-foreground">
        Select a chat or start a new one.
      </p>
    </div>
  );
}
