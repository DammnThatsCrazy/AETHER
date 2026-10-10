/**
 * Auth0 Universal Login entry point. The staging operator (first-admin
 * bootstrap email) and invited teammates have no password registered with the
 * backend; they sign in through Auth0 and /callback links them to their
 * existing user. Without this button the only way in was /signup, which
 * creates a new paid-plan tenant.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@aether/ui";
import { AuthProvider } from "@aether-app/features/auth";
import { LoginPage } from "./login-page";

const loginWithRedirect = vi.fn(() => Promise.resolve());
vi.mock("@auth0/auth0-react", () => ({
  useAuth0: () => ({ loginWithRedirect }),
}));

const envState = vi.hoisted(() => ({
  VITE_AETHER_ENV: "staging",
  VITE_AUTH0_DOMAIN: undefined as string | undefined,
  VITE_AUTH0_CLIENT_ID: undefined as string | undefined,
}));
vi.mock("@aether-app/lib/env", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@aether-app/lib/env")>();
  // Only the Auth0 settings vary per test; everything else is the real env.
  const env = new Proxy(actual.env, {
    get: (target, key: string) =>
      key in envState
        ? envState[key as keyof typeof envState]
        : target[key as keyof typeof target],
  });
  return { ...actual, env };
});

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: {
    auth: { login: vi.fn(), developmentSession: vi.fn() },
    me: { profile: vi.fn() },
  },
}));

function renderLogin() {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <LoginPage />
        </MemoryRouter>
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe("LoginPage Auth0 sign-in", () => {
  beforeEach(() => {
    sessionStorage.clear();
    loginWithRedirect.mockClear();
    envState.VITE_AUTH0_DOMAIN = undefined;
    envState.VITE_AUTH0_CLIENT_ID = undefined;
  });

  it("starts Auth0 Universal Login when the build carries Auth0 settings", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    renderLogin();

    await userEvent.click(screen.getByRole("button", { name: "Continue with Olympus sign-in" }));

    expect(loginWithRedirect).toHaveBeenCalledTimes(1);
  });

  it("is not offered without Auth0 settings (no Auth0Provider is mounted)", () => {
    renderLogin();

    expect(screen.queryByRole("button", { name: "Continue with Olympus sign-in" })).toBeNull();
  });
});
