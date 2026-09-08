/**
 * Public marketing shell handoff: the tenant app's /login accepts a prefilled
 * email carried as `?email=...`. The value is applied only as the field's
 * initial state so user typing is never clobbered by an effect. The marketing→
 * signup leg is also covered here: when /login carries a genuine post-auth
 * redirect (RequireAuth round-trip of a connect deep link), the "Create one"
 * affordance forwards it into /signup so a brand-new account still lands on the
 * provider the visitor came to connect.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ThemeProvider } from "@aether/ui";
import { AuthProvider } from "@aether-app/features/auth";
import { LoginPage, resolvePostAuthRedirect } from "./login-page";

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: {
    auth: { login: vi.fn(), developmentSession: vi.fn() },
    me: { profile: vi.fn() },
  },
}));

/** Captures the location SignupPage would be opened at after "Create one". */
function SignupProbe() {
  const location = useLocation();
  return (
    <div data-testid="signup-probe">
      {location.pathname}
      {location.search}
    </div>
  );
}

function renderLogin(initialEntry: string) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupProbe />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe("LoginPage public-handoff prefill", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("prefills the email field from the ?email= query parameter", () => {
    renderLogin("/login?email=person%40example.com");

    expect(screen.getByLabelText("Email address")).toHaveValue(
      "person@example.com",
    );
  });

  it("leaves the email field empty when no ?email= is present", () => {
    renderLogin("/login");

    expect(screen.getByLabelText("Email address")).toHaveValue("");
  });
});

describe("LoginPage marketing→signup redirect continuity", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("forwards a genuine connect-intent redirect into the /signup URL", async () => {
    const user = userEvent.setup();
    renderLogin(
      "/login?redirect=%2Fsettings%2Fintegrations%3Ffamily%3Dgoogle_ads%26experience%3Dadvertising_campaigns%26intent%3Dconnect",
    );

    await user.click(screen.getByRole("button", { name: "Create one" }));

    const probe = await screen.findByTestId("signup-probe");
    expect(probe.textContent).toBe(
      "/signup?redirect=%2Fsettings%2Fintegrations%3Ffamily%3Dgoogle_ads%26experience%3Dadvertising_campaigns%26intent%3Dconnect",
    );
  });

  it("does not tack a ?redirect=/settings fallback onto a plain signup link", async () => {
    const user = userEvent.setup();
    renderLogin("/login?email=person%40example.com");

    await user.click(screen.getByRole("button", { name: "Create one" }));

    const probe = await screen.findByTestId("signup-probe");
    expect(probe.textContent).toBe("/signup");
  });
});

describe("resolvePostAuthRedirect", () => {
  it("accepts an internal deep link with query params (RequireAuth round-trip)", () => {
    expect(
      resolvePostAuthRedirect(
        "/settings/integrations?family=google_ads&intent=connect",
      ),
    ).toBe("/settings/integrations?family=google_ads&intent=connect");
  });

  it("falls back to the tenant home for empty or foreign redirect values", () => {
    expect(resolvePostAuthRedirect(null)).toBe("/settings");
    expect(resolvePostAuthRedirect("")).toBe("/settings");
    expect(resolvePostAuthRedirect("//evil.example")).toBe("/settings");
    expect(resolvePostAuthRedirect("https://evil.example")).toBe("/settings");
  });

  it("rejects backslash-authority and control-character redirect variants", () => {
    // URL parsers normalize `/\…` into a `//` scheme-relative authority and a
    // leading `\` into a path escape; both must stay on the tenant home.
    expect(resolvePostAuthRedirect("\\evil.example")).toBe("/settings");
    expect(resolvePostAuthRedirect("/\\evil.example")).toBe("/settings");
    expect(resolvePostAuthRedirect("/\\\\evil.example")).toBe("/settings");
    expect(resolvePostAuthRedirect("/settings\\@evil.example")).toBe("/settings");
    expect(resolvePostAuthRedirect("/settings\r\nLocation:https://evil.example")).toBe(
      "/settings",
    );
  });
});
