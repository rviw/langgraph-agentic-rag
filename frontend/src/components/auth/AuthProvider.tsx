import { useEffect, useState, type PropsWithChildren } from "react";

import { AuthContext, type AuthState } from "@/hooks/useAuth";
import { supabase } from "@/lib/supabase";

export function AuthProvider({ children }: PropsWithChildren) {
  const [authState, setAuthState] = useState<AuthState>({
    session: null,
    isLoading: true,
  });

  useEffect(() => {
    // The subscription fires with the restored session, so it also ends loading.
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setAuthState({ session, isLoading: false });
    });

    return () => subscription.unsubscribe();
  }, []);

  return <AuthContext value={authState}>{children}</AuthContext>;
}
