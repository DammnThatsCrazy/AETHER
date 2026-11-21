/**
 * With Auth0 configured, /signup opens Auth0's hosted sign-up (Google or email
 * and password) and remembers where the new account should land: billing with
 * the plan chosen on the pricing page, an explicit ?redirect=, or onboarding.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider, ToastProvider } from "@aether/ui";
import { AuthProvider } from "@aether-app/features/auth";
import { readPostAuthDestination } from "@aether-app/features/auth/post-auth-redirect";
import { SignupPage } from "./signup-page";

const loginWithRedirect = vi.fn((_options?: unknown) => Promise.resolve());
vi.mock("@auth0/auth0-react", () => ({
  useAuth0: () => ({ loginWithRedirect }),
}));

const envState = vi.hoisted(() => ({
  VITE_AETHER_ENV: "staging",
  VITE_AUTH0_DOMAIN: undefined as string | undefined,
  VITE_AUTH0_CLIENT_ID: undefined as string | undefined,
  VITE_AUTH0_SOCIAL_CONNECTIONS: undefined as string | undefined,
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
  api: {
    auth: { register: vi.fn(), verifyEmail: vi.fn(), developmentSession: vi.fn() },
    me: { profile: vi.fn() },
  },
}));

function renderSignup(entry: string) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[entry]}>
            <SignupPage />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe("SignupPage with Auth0", () => {
  beforeEach(() => {
    sessionStorage.clear();
    loginWithRedirect.mockClear();
    loginWithRedirect.mockImplementation(() => Promise.resolve());
    envState.VITE_AUTH0_DOMAIN = "tenant.us.auth0.com";
    envState.VITE_AUTH0_CLIENT_ID = "client";
    envState.VITE_AUTH0_SOCIAL_CONNECTIONS = undefined;
  });

  async function continueWithEmail(address = "new@company.com") {
    await userEvent.type(screen.getByLabelText("Work email"), address);
    await userEvent.click(screen.getByRole("button", { name: "Continue with email" }));
  }

  it("opens Auth0 sign-up for the work email and keeps the chosen plan for billing", async () => {
    renderSignup("/signup?plan=beta");
    expect(screen.getByText(/Plan: Beta/)).toBeTruthy();
    expect(loginWithRedirect).not.toHaveBeenCalled();
    await continueWithEmail();
    await waitFor(() =>
      expect(loginWithRedirect).toHaveBeenCalledWith({
        authorizationParams: { screen_hint: "signup", login_hint: "new@company.com" },
      }),
    );
    expect(readPostAuthDestination()).toBe("/billing?plan=beta");
  });

  it("keeps the annual interval with the plan", async () => {
    renderSignup("/signup?plan=gamma&interval=annual");
    await continueWithEmail();
    await waitFor(() => expect(loginWithRedirect).toHaveBeenCalled());
    expect(readPostAuthDestination()).toBe("/billing?plan=gamma&interval=annual");
  });

  it("lands on onboarding without a plan, or on a safe ?redirect=", async () => {
    renderSignup("/signup");
    await continueWithEmail();
    await waitFor(() => expect(loginWithRedirect).toHaveBeenCalled());
    expect(readPostAuthDestination()).toBe("/onboarding");
  });

  it("ignores an unknown plan and an off-site redirect", async () => {
    renderSignup("/signup?plan=enterprise&redirect=//evil.example");
    await continueWithEmail();
    await waitFor(() => expect(loginWithRedirect).toHaveBeenCalled());
    expect(readPostAuthDestination()).toBe("/onboarding");
  });

  it("honors an explicit ?redirect=/settings over a provider hand-off", async () => {
    renderSignup("/signup?redirect=/settings&family=google_ads&experience=advertising_campaigns");
    await continueWithEmail();
    await waitFor(() => expect(loginWithRedirect).toHaveBeenCalled());
    expect(readPostAuthDestination()).toBe("/settings");
  });

  it("keeps a marketing provider hand-off, as the email form does", async () => {
    renderSignup("/signup?family=google_ads&experience=advertising_campaigns&intent=connect");
    await continueWithEmail();
    await waitFor(() => expect(loginWithRedirect).toHaveBeenCalled());
    expect(readPostAuthDestination()).toMatch(/^\/settings\/integrations\?/);
    expect(readPostAuthDestination()).toContain("family=google_ads");
  });

  it("offers a retry when Auth0 cannot be reached", async () => {
    loginWithRedirect.mockImplementation(() => Promise.reject(new Error("offline")));
    renderSignup("/signup?plan=gamma");
    await continueWithEmail();
    expect(await screen.findByText("Could not reach the sign-up service.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue with email" })).toBeTruthy();
  });

  it("keeps the email form when the build has no Auth0 settings", () => {
    envState.VITE_AUTH0_DOMAIN = undefined;
    envState.VITE_AUTH0_CLIENT_ID = undefined;
    renderSignup("/signup");

    expect(loginWithRedirect).not.toHaveBeenCalled();
    expect(screen.queryByText("Every relationship and every perspective")).toBeNull();
  });

  it("signs up with Google or Apple through their Auth0 connections", async () => {
    envState.VITE_AUTH0_SOCIAL_CONNECTIONS = "google=aether-staging-google,apple=aether-staging-apple";
    renderSignup("/signup?plan=delta");
    await userEvent.click(screen.getByRole("button", { name: "Continue with Apple" }));
    expect(loginWithRedirect).toHaveBeenCalledWith({
      authorizationParams: { screen_hint: "signup", connection: "aether-staging-apple" },
    });
    expect(readPostAuthDestination()).toBe("/billing?plan=delta");
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeTruthy();
  });

  it("asks for a valid work email before opening sign-up", async () => {
    renderSignup("/signup");
    await continueWithEmail("nope");
    expect(await screen.findByText("Enter a valid work email.")).toBeTruthy();
    expect(loginWithRedirect).not.toHaveBeenCalled();
  });
});
