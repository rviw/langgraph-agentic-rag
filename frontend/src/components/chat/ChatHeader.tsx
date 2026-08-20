import { ArrowLeftIcon, PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";
import { Link } from "react-router";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";

type ChatHeaderProps = {
  chatId?: string;
  title?: string;
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
};

export function ChatHeader({
  chatId,
  title,
  isSidebarOpen,
  onToggleSidebar,
}: ChatHeaderProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3">
      {chatId && (
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Back to chats"
          asChild
        >
          <Link to="/chats">
            <ArrowLeftIcon aria-hidden="true" />
          </Link>
        </Button>
      )}

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="hidden md:inline-flex"
        aria-label={isSidebarOpen ? "Hide chats" : "Show chats"}
        aria-controls="chat-sidebar"
        aria-expanded={isSidebarOpen}
        onClick={onToggleSidebar}
      >
        {isSidebarOpen ? (
          <PanelLeftCloseIcon aria-hidden="true" />
        ) : (
          <PanelLeftOpenIcon aria-hidden="true" />
        )}
      </Button>

      <span className="min-w-0 flex-1 truncate text-sm font-medium">
        {chatId ? (title ?? "Chat") : "LangGraph Agentic RAG"}
      </span>

      <ThemeToggle />
    </header>
  );
}
