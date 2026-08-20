import { useState, type FormEvent } from "react";

import { ExternalProviderDisclosure } from "@/components/auth/ExternalProviderDisclosure";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { supabase } from "@/lib/supabase";

export function LoginPage() {
  const [isSignUp, setIsSignUp] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [hasAcceptedDisclosure, setHasAcceptedDisclosure] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "").trim();
    const password = String(formData.get("password") ?? "");

    try {
      const { error } = isSignUp
        ? await supabase.auth.signUp({ email, password })
        : await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setErrorMessage(
          isSignUp
            ? "Couldn't create your account. Check your details and try again."
            : "Couldn't sign in. Check your email and password.",
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  function toggleMode() {
    setIsSignUp((current) => !current);
    setErrorMessage(null);
    setHasAcceptedDisclosure(false);
  }

  return (
    <section className="mx-auto w-full max-w-md overflow-hidden rounded-xl bg-card text-sm text-card-foreground ring-1 ring-foreground/10">
      <header className="grid gap-1 p-4 text-center">
        <h1 className="font-heading text-xl font-semibold tracking-tight">
          {isSignUp ? "Create an account" : "Sign in"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {isSignUp
            ? "Create an account to start a chat."
            : "Sign in to continue your chats."}
        </p>
      </header>

      <form className="flex flex-col gap-5 px-4 pb-4" onSubmit={handleSubmit}>
        {errorMessage && (
          <Alert className="rounded-lg border bg-card px-3 py-2 text-left">
            {errorMessage}
          </Alert>
        )}

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Email</span>
          <Input
            name="email"
            type="email"
            autoComplete="email"
            disabled={isSubmitting}
            placeholder="you@example.com"
            required
          />
        </label>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Password</span>
          <Input
            name="password"
            type="password"
            autoComplete={isSignUp ? "new-password" : "current-password"}
            disabled={isSubmitting}
            required
          />
        </label>

        {isSignUp && (
          <div className="grid gap-4 rounded-lg border p-4">
            <div className="grid gap-1">
              <h2 className="font-medium">External provider disclosure</h2>
              <p className="text-muted-foreground">
                You must accept this disclosure to create an account.
              </p>
            </div>
            <ExternalProviderDisclosure />
            <label className="flex items-start gap-3 rounded-lg border p-3">
              <input
                type="checkbox"
                checked={hasAcceptedDisclosure}
                disabled={isSubmitting}
                className="mt-0.5 size-4 shrink-0 accent-primary"
                onChange={(event) =>
                  setHasAcceptedDisclosure(event.currentTarget.checked)
                }
              />
              <span>
                I agree to the external provider disclosure and data processing
                described above.
              </span>
            </label>
          </div>
        )}

        <Button
          type="submit"
          className="w-full"
          aria-busy={isSubmitting}
          disabled={isSubmitting || (isSignUp && !hasAcceptedDisclosure)}
        >
          {isSubmitting && (
            <Spinner data-icon="inline-start" aria-hidden="true" />
          )}
          {isSignUp ? "Create account" : "Sign in"}
        </Button>
      </form>

      <footer className="flex items-center justify-center gap-1 border-t bg-muted/50 p-4 text-sm">
        <span className="text-muted-foreground">
          {isSignUp ? "Already have an account?" : "New to the app?"}
        </span>
        <Button
          variant="link"
          size="sm"
          disabled={isSubmitting}
          onClick={toggleMode}
        >
          {isSignUp ? "Sign in" : "Create account"}
        </Button>
      </footer>
    </section>
  );
}
