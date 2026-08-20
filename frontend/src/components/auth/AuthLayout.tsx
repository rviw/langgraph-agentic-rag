import { Navigate, Outlet, useLocation } from "react-router";

import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/useAuth";

export function AuthLayout() {
  const { session, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <main className="flex min-h-svh items-center justify-center">
        <Spinner aria-label="Loading" />
      </main>
    );
  }

  if (session) {
    const state = location.state as { from?: string } | null;
    return (
      <Navigate
        to={state?.from ?? "/chats"}
        replace
      />
    );
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-6">
      <div className="w-full max-w-md">
        <Outlet />
      </div>
    </main>
  );
}
