/**
 * Public marketing shell handoff: the tenant app's /signup accepts prefilled
 * name and email carried as `?name=...&email=...`, applied only as the step-1
 * fields' initial state. The marketing→signup provider-prefill leg is covered
 * here too: a brand-new visitor who creates their account from a marketing deep
 * link lands on the provider they came to connect (/settings/integrations?…)
 * after completing the OTP flow, either via an explicit ?redirect= or via the
 * ?family/experience/intent handoff params themselves.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ThemeProvider, ToastProvider } from "@aether/ui";
import { AuthProvider } from "@aether-app/features/auth";
import { SignupPage } from "./signup-page";

const authApi = vi.hoisted(() => ({
  register: vi.fn(),
  verifyEmail: vi.fn(),
  developmentSession: vi.fn(),
  profile: vi.fn(),
}));

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: {
    auth: {
      register: authApi.register,
      verifyEmail: authApi.verifyEmail,
      developmentSession: authApi.developmentSession,
    },
    me: { profile: authApi.profile },
  },
}));

const SESSION_GRANT = {
  session: {
    session_id: "sess_test",
    token: "sess_1",
    idle_expires_at: "2026-09-08T00:00:00Z",
    absolute_expires_at: "2026-09-09T00:00:00Z",
  },
};

/** Captures the location the /login link opens, to assert params are kept. */
function LoginProbe() {
  const location = useLocation();
  return (
    <div data-testid="login-probe">
      {location.pathname}
      {location.search}
    </div>
  );
}

function renderSignup(initialEntry: string) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialEntry]}>
            <Routes>
              <Route path="/signup" element={<SignupPage />} />
              <Route path="/settings" element={<div>SETTINGS LANDING</div>} />
              <Route
                path="/settings/integrations"
                element={<div>INTEGRATIONS LANDING</div>}
              />
              <Route path="/login" element={<LoginProbe />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </ThemeProvider>,
  );
}

/** Drives step 1 (register) → step 2 (OTP) → step 3 (all set). */
async function completeSignupFlow() {
  const user = userEvent.setup();
  // Controlled field changes preserve the registration payload while avoiding
  // a per-keystroke delay that made this deterministic flow exceed Vitest's
  // five-second default when the full workspace suite is under load.
  fireEvent.change(screen.getByLabelText("Full name"), {
    target: { value: "Ada Lovelace" },
  });
  fireEvent.change(screen.getByLabelText("Work email"), {
    target: { value: "ada@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "password123" },
  });
  await user.click(screen.getByRole("button", { name: "Continue →" }));

  await screen.findByText("Check your email");
  fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), {
    clipboardData: { getData: () => "123456" },
  });
  await user.click(screen.getByRole("button", { name: /verify.*continue/i }));
  await screen.findByText("You're all set");
}

describe("SignupPage public-handoff prefill", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("prefills name and email on step 1 from the query parameters", () => {
    renderSignup("/signup?name=Ada&email=ada%40example.com");

    expect(screen.getByLabelText("Full name")).toHaveValue("Ada");
    expect(screen.getByLabelText("Work email")).toHaveValue("ada@example.com");
  });

  it("starts step 1 with empty fields when no query parameters are present", () => {
    renderSignup("/signup");

    expect(screen.getByLabelText("Full name")).toHaveValue("");
    expect(screen.getByLabelText("Work email")).toHaveValue("");
  });
});

describe("SignupPage post-auth target (marketing provider handoff)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    authApi.register.mockReset().mockResolvedValue({} as never);
    authApi.verifyEmail.mockReset().mockResolvedValue(SESSION_GRANT as never);
    authApi.profile.mockReset().mockResolvedValue({
      tenant_id: "t1",
      contact_email: "ada@example.com",
      name: "Ada Lovelace",
    } as never);
  });

  it("honors an explicit internal ?redirect on successful account creation", async () => {
    renderSignup(
      "/signup?redirect=%2Fsettings%2Fintegrations%3Ffamily%3Dgoogle_ads%26experience%3Dadvertising_campaigns%26intent%3Dconnect",
    );
    await completeSignupFlow();

    await userEvent.click(
      screen.getByRole("button", { name: "Go to dashboard" }),
    );

    expect(await screen.findByText("INTEGRATIONS LANDING")).toBeInTheDocument();
  });

  it('lands a family/experience/intent handoff on the provider via "Skip for now" (no redirect)', async () => {
    renderSignup(
      "/signup?family=google_ads&experience=advertising_campaigns&intent=connect",
    );
    await completeSignupFlow();

    await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(await screen.findByText("INTEGRATIONS LANDING")).toBeInTheDocument();
  });

  it("lands a plain signup on the tenant home", async () => {
    renderSignup("/signup");
    await completeSignupFlow();

    await userEvent.click(
      screen.getByRole("button", { name: "Go to dashboard" }),
    );

    expect(await screen.findByText("SETTINGS LANDING")).toBeInTheDocument();
  });

  it("never lands on a foreign redirect after signup — falls back safely", async () => {
    renderSignup("/signup?redirect=https%3A%2F%2Fevil.example%2Fphish");
    await completeSignupFlow();

    await userEvent.click(
      screen.getByRole("button", { name: "Go to dashboard" }),
    );

    expect(await screen.findByText("SETTINGS LANDING")).toBeInTheDocument();
  });

  it("preserves the current ?redirect and handoff params on the /login link", async () => {
    renderSignup(
      "/signup?redirect=%2Fsettings%2Fintegrations%3Ffamily%3Dgoogle_ads%26intent%3Dconnect&name=Ada&email=ada%40example.com",
    );

    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const probe = await screen.findByTestId("login-probe");
    expect(probe.textContent).toContain("/login?redirect=");
    expect(probe.textContent).toContain(
      "redirect=%2Fsettings%2Fintegrations%3Ffamily%3Dgoogle_ads%26intent%3Dconnect",
    );
  });
});
