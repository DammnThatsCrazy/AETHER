/**
 * The extra codes in Aether sign-in:
 *  - a first-time SSO sign-up enters the code emailed to it before a workspace
 *    exists (/callback), and
 *  - a user with two-step verification enters an authenticator code after the
 *    password (/login) or SSO (/callback) step.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ThemeProvider } from "@aether/ui";
import { api } from "@aether-app/lib/api/endpoints";
import { CallbackPage } from "@aether-app/pages/callback";
import { LoginPage } from "@aether-app/pages/login/login-page";

vi.mock("@auth0/auth0-react", () => ({
  useAuth0: () => ({
    isLoading: false,
    isAuthenticated: true,
    error: undefined,
    getAccessTokenSilently: () => Promise.resolve("jwt-1"),
    loginWithRedirect: vi.fn(),
    logout: vi.fn(() => Promise.resolve()),
  }),
}));

const sessionLogin = vi.fn(() => Promise.resolve());
vi.mock("@aether-app/features/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@aether-app/features/auth")>()),
  useAuth: () => ({ sessionLogin, apiKeyLogin: vi.fn() }),
}));

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: { auth: { ssoCallback: vi.fn(), mfaVerify: vi.fn(), login: vi.fn(), developmentSession: vi.fn() } },
}));

const SESSION = { session: { token: "sess_1", session_id: "s1", idle_expires_at: "", absolute_expires_at: "" } };

function Landing() {
  const location = useLocation();
  return <div data-testid="landing">{location.pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/callback" element={<CallbackPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Landing />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  sessionLogin.mockClear();
  vi.mocked(api.auth.ssoCallback).mockReset();
  vi.mocked(api.auth.mfaVerify).mockReset();
  vi.mocked(api.auth.login).mockReset();
});

describe("first-time sign-up code", () => {
  it("asks for the emailed code and finishes with the same token", async () => {
    vi.mocked(api.auth.ssoCallback)
      .mockResolvedValueOnce({ signup_verification_required: true, email: "new@co.com" })
      .mockResolvedValueOnce(SESSION);
    const user = userEvent.setup();
    renderAt("/callback");

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeTruthy();
    expect(screen.getByText("new@co.com")).toBeTruthy();
    await user.type(screen.getByLabelText("Sign-up code"), "123456");
    await user.click(screen.getByRole("button", { name: "Create my workspace" }));

    await waitFor(() => expect(sessionLogin).toHaveBeenCalled());
    expect(api.auth.ssoCallback).toHaveBeenLastCalledWith("jwt-1", "123456");
    expect(await screen.findByTestId("landing")).toBeTruthy();
  });

  it("keeps the person on the code step when the code is wrong", async () => {
    vi.mocked(api.auth.ssoCallback)
      .mockResolvedValueOnce({ signup_verification_required: true, email: "new@co.com" })
      .mockRejectedValueOnce(Object.assign(new Error("Invalid or expired code."), { status: 400 }));
    const user = userEvent.setup();
    renderAt("/callback");
    await user.type(await screen.findByLabelText("Sign-up code"), "000000");
    await user.click(screen.getByRole("button", { name: "Create my workspace" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(sessionLogin).not.toHaveBeenCalled();
  });

  it("can send a new code", async () => {
    vi.mocked(api.auth.ssoCallback)
      .mockResolvedValueOnce({ signup_verification_required: true, email: "new@co.com" })
      .mockResolvedValueOnce({ signup_verification_required: true, email: "new@co.com" });
    const user = userEvent.setup();
    renderAt("/callback");
    await user.click(await screen.findByRole("button", { name: "Send a new code" }));
    expect(await screen.findByText("We sent a new code.")).toBeTruthy();
    expect(api.auth.ssoCallback).toHaveBeenLastCalledWith("jwt-1");
  });
});

describe("two-step verification", () => {
  it("stops an SSO sign-in for the authenticator code", async () => {
    vi.mocked(api.auth.ssoCallback).mockResolvedValueOnce({ mfa_required: true, mfa_challenge: "ch_1" });
    vi.mocked(api.auth.mfaVerify).mockResolvedValueOnce(SESSION);
    const user = userEvent.setup();
    renderAt("/callback");

    await user.type(await screen.findByLabelText("Authentication code"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(sessionLogin).toHaveBeenCalled());
    expect(api.auth.mfaVerify).toHaveBeenCalledWith("ch_1", "654321");
  });

  it("stops a password sign-in and accepts a recovery code", async () => {
    vi.mocked(api.auth.login).mockResolvedValueOnce({ mfa_required: true, mfa_challenge: "ch_2" });
    vi.mocked(api.auth.mfaVerify).mockResolvedValueOnce(SESSION);
    const user = userEvent.setup();
    renderAt("/login");

    await user.type(screen.getByLabelText("Work email"), "a@co.com");
    await user.click(screen.getByRole("button", { name: "Sign in with email" }));
    await user.type(await screen.findByLabelText("Password"), "pw12345678");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Two-step verification" })).toBeTruthy();
    expect(sessionLogin).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Use a recovery code" }));
    await user.type(screen.getByLabelText("Recovery code"), "abcd-efgh");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(sessionLogin).toHaveBeenCalled());
    expect(api.auth.mfaVerify).toHaveBeenCalledWith("ch_2", "abcd-efgh");
  });
});
