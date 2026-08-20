import type { Page, Route } from "@playwright/test";

export const SESSION_USER = {
  id: "6f1d6a5e-6b0f-4f4e-9f0a-2b5d4e6a7c81",
  email: "member@example.test",
};

function session() {
  return {
    access_token: "test-access-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "test-refresh-token",
    user: {
      id: SESSION_USER.id,
      aud: "authenticated",
      role: "authenticated",
      email: SESSION_USER.email,
      app_metadata: {},
      user_metadata: {},
      created_at: new Date().toISOString(),
    },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/** Route Supabase Auth calls to local stubs and record what was requested. */
export async function stubSupabaseAuth(
  page: Page,
  options: { signUpError?: string } = {},
) {
  const calls: { path: string; body: unknown }[] = [];

  await page.route("**/supabase/auth/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/supabase/auth/v1", "");
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = null;
    }
    calls.push({ path, body });

    if (path === "/signup" && options.signUpError) {
      await fulfillJson(route, { error: options.signUpError }, 400);
      return;
    }
    if (path === "/signup" || path.startsWith("/token")) {
      await fulfillJson(route, session());
      return;
    }
    if (path === "/logout") {
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    if (path === "/user") {
      await fulfillJson(route, { user: session().user });
      return;
    }
    await fulfillJson(route, {});
  });

  return calls;
}

/** Start the page already signed in by seeding the stored Supabase session. */
export async function signIn(page: Page) {
  const stored = {
    ...session(),
    provider_token: null,
    provider_refresh_token: null,
  };
  await page.addInitScript(
    ([value]) => {
      window.localStorage.setItem(
        "sb-127-auth-token",
        JSON.stringify(value),
      );
    },
    [stored],
  );
}
