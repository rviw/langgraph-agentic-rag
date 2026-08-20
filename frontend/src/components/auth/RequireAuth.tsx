import type { Session } from "@supabase/supabase-js";
import { Navigate, Outlet, useLocation } from "react-router";

import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/useAuth";

export type AuthenticatedOutletContext = {
  session: Session;
};

export function RequireAuth() {
  const { session, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <main className="flex min-h-svh items-center justify-center">
        <Spinner aria-label="Loading" />
      </main>
    );
  }

  if (!session) {
    // Remember where the visitor was headed so sign-in can return them.
    const from = `${location.pathname}${location.search}${location.hash}`;
    return (
      <Navigate
        to="/login"
        replace
        state={{ from }}
      />
    );
  }

  return <Outlet context={{ session } satisfies AuthenticatedOutletContext} />;
}
