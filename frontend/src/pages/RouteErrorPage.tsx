import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function RouteErrorPage() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-sm font-medium text-destructive">Application error</p>
      <h1 className="text-3xl font-semibold tracking-tight">
        Something went wrong
      </h1>
      <p className="max-w-md text-sm text-muted-foreground">
        Reload the page to try again.
      </p>
      <Button asChild variant="link" className="h-auto p-0 underline">
        <Link to="/chats">Go to chats</Link>
      </Button>
    </main>
  );
}
