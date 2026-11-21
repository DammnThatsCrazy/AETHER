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
  VITE_AUTH0_SOCIAL_CONNECTIONS: undefined as string | undefined,
  VITE_AUTH0_ENTERPRISE_CONNECTIONS: undefined as string | undefined,
  VITE_AUTH0_PASSWORDLESS_CONNECTION: undefined as string | undefined,
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
    envState.VITE_AUTH0_SOCIAL_CONNECTIONS = undefined;
    envState.VITE_AUTH0_ENTERPRISE_CONNECTIONS = undefined;
    envState.VITE_AUTH0_PASSWORDLESS_CONNECTION = undefined;
  });

  async function toPasswordStep(address = "teammate@example.com") {
    await userEvent.type(screen.getByLabelText("Work email"), address);
    await userEvent.click(screen.getByRole("button", { name: "Sign in with email" }));
  }

  it("starts Auth0 Universal Login when the build carries Auth0 settings", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    renderLogin();
    await toPasswordStep();

    await userEvent.click(screen.getByRole("button", { name: "Use another sign-in method" }));

    expect(loginWithRedirect).toHaveBeenCalledWith({
      authorizationParams: { login_hint: "teammate@example.com" },
    });
  });

  it("is not offered without Auth0 settings (no Auth0Provider is mounted)", async () => {
    renderLogin();
    await toPasswordStep();

    expect(screen.queryByRole("button", { name: "Use another sign-in method" })).toBeNull();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("sends a company domain straight to its enterprise connection", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    envState.VITE_AUTH0_ENTERPRISE_CONNECTIONS = "acme.com=acme-okta";
    renderLogin();
    await toPasswordStep("dana@ACME.com");

    expect(loginWithRedirect).toHaveBeenCalledWith({
      authorizationParams: { connection: "acme-okta", login_hint: "dana@ACME.com" },
    });
    expect(screen.queryByLabelText("Password")).toBeNull();
  });

  it("offers an emailed sign-in code when a passwordless connection is set", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    envState.VITE_AUTH0_PASSWORDLESS_CONNECTION = "email";
    renderLogin();
    await toPasswordStep();

    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in code" }));

    expect(loginWithRedirect).toHaveBeenCalledWith({
      authorizationParams: { connection: "email", login_hint: "teammate@example.com" },
    });
  });

  it("shows the same next step for every non-SSO email (no account lookup)", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    renderLogin();
    await toPasswordStep("nobody@unknown.example");

    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use another sign-in method" })).toBeTruthy();
  });

  it("sends a social sign-in straight to its Auth0 connection", async () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    envState.VITE_AUTH0_SOCIAL_CONNECTIONS = "google=aether-staging-google,slack=aether-staging-slack";
    renderLogin();

    await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    expect(loginWithRedirect).toHaveBeenCalledWith({
      authorizationParams: { connection: "aether-staging-google" },
    });
    expect(screen.getByRole("button", { name: "Continue with Slack" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Continue with Apple" })).toBeNull();
  });

  it("ignores malformed social connection entries", () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    envState.VITE_AUTH0_SOCIAL_CONNECTIONS = "google=,=x,apple,slack=a=b,microsoft=aether-staging-microsoft";
    renderLogin();

    expect(screen.getByRole("button", { name: "Continue with Microsoft" })).toBeTruthy();
    for (const name of ["Continue with Google", "Continue with Apple", "Continue with Slack"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("offers no social sign-in when no Auth0 social connection is enabled", () => {
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    renderLogin();

    expect(screen.queryByRole("button", { name: "Continue with Google" })).toBeNull();
  });

  it("offers no social sign-in without Auth0 even if connections are listed", () => {
    envState.VITE_AUTH0_SOCIAL_CONNECTIONS = "google=aether-staging-google";
    renderLogin();

    expect(screen.queryByRole("button", { name: "Continue with Google" })).toBeNull();
  });
});
