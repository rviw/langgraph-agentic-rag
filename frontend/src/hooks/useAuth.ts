import type { Session } from "@supabase/supabase-js";
import { createContext, useContext } from "react";

export type AuthState = {
  session: Session | null;
  isLoading: boolean;
};

export const AuthContext = createContext<AuthState>({
  session: null,
  isLoading: true,
});

export function useAuth() {
  return useContext(AuthContext);
}
