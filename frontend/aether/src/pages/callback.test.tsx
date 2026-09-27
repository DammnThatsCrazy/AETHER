/**
 * After Auth0 returns, /callback exchanges the token for a session and lands
 * on the destination remembered before the hand-off (for example billing with
 * the plan chosen on the pricing page), or the tenant home.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ThemeProvider } from "@aether/ui";
import { rememberPostAuthDestination } from "@aether-app/features/auth/post-auth-redirect";
import { CallbackPage } from "./callback";

vi.mock("@auth0/auth0-react", () => ({
  useAuth0: () => ({
    isLoading: false,
    isAuthenticated: true,
    error: undefined,
    getAccessTokenSilently: () => Promise.resolve("jwt"),
  }),
}));

const sessionLogin = vi.fn(() => Promise.resolve());
vi.mock("@aether-app/features/auth", () => ({
  useAuth: () => ({ sessionLogin, apiKeyLogin: vi.fn() }),
  resolveAuthGrant: () => ({ kind: "session", session: { token: "sess_1" } }),
}));

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: { auth: { ssoCallback: vi.fn(() => Promise.resolve({ session: { token: "sess_1" } })) } },
}));

function Landing() {
  const location = useLocation();
  return <div data-testid="landing">{location.pathname + location.search}</div>;
}

function renderCallback() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/callback"]}>
        <Routes>
          <Route path="/callback" element={<CallbackPage />} />
          <Route path="*" element={<Landing />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("CallbackPage destination", () => {
  beforeEach(() => {
    sessionStorage.clear();
    sessionLogin.mockClear();
  });

  it("lands on the remembered destination", async () => {
    rememberPostAuthDestination("/billing?plan=beta");
    renderCallback();

    expect((await screen.findByTestId("landing")).textContent).toBe("/billing?plan=beta");
    expect(sessionLogin).toHaveBeenCalledTimes(1);
  });

  it("lands on the tenant home when nothing was remembered", async () => {
    renderCallback();

    expect((await screen.findByTestId("landing")).textContent).toBe("/settings");
  });
});
