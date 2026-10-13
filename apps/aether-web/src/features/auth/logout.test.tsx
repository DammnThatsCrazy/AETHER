/**
 * Signing out must end the Auth0 session too; otherwise the next "Continue
 * with Olympus sign-in" silently signs the same user back in.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, SESSION_TOKEN_KEY, useAuth } from "@aether-app/features/auth";

const auth0Logout = vi.fn(() => Promise.resolve());
vi.mock("@auth0/auth0-react", () => ({
  useAuth0: () => ({ logout: auth0Logout }),
}));

const envState = vi.hoisted(() => ({
  VITE_AUTH0_DOMAIN: undefined as string | undefined,
  VITE_AUTH0_CLIENT_ID: undefined as string | undefined,
  VITE_AUTH0_LOGOUT_URI: undefined as string | undefined,
}));
vi.mock("@aether-app/lib/env", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@aether-app/lib/env")>();
  const env = new Proxy(actual.env, {
    get: (target, key: string) =>
      key in envState
        ? envState[key as keyof typeof envState]
        : target[key as keyof typeof target],
  });
  return { ...actual, env };
});

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: { me: { profile: vi.fn() } },
}));

function SignOut() {
  const { logout } = useAuth();
  return <button onClick={() => void logout()}>Sign out</button>;
}

function renderSignOut() {
  render(
    <AuthProvider>
      <SignOut />
    </AuthProvider>,
  );
}

describe("logout", () => {
  beforeEach(() => {
    sessionStorage.clear();
    auth0Logout.mockClear();
    envState.VITE_AUTH0_DOMAIN = undefined;
    envState.VITE_AUTH0_CLIENT_ID = undefined;
    envState.VITE_AUTH0_LOGOUT_URI = undefined;
  });

  it("ends the Auth0 session and returns to the configured logout URI", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    envState.VITE_AUTH0_LOGOUT_URI = "https://aether.example/app/login";
    sessionStorage.setItem(SESSION_TOKEN_KEY, "sess_x");
    renderSignOut();

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() =>
      expect(auth0Logout).toHaveBeenCalledWith({
        logoutParams: { returnTo: "https://aether.example/app/login" },
      }),
    );
    expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull();
  });

  it("leaves Auth0 alone when the build has no Auth0 settings", async () => {
    renderSignOut();

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull());
    expect(auth0Logout).not.toHaveBeenCalled();
  });
});
