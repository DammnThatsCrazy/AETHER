import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@aether/ui";
import { api } from "@aether-app/lib/api/endpoints";
import { TwoStepVerificationBlock } from "./two-step-section";

vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: {
    me: {
      mfa: {
        status: vi.fn(),
        enroll: vi.fn(),
        confirm: vi.fn(),
        disable: vi.fn(),
        regenerateRecoveryCodes: vi.fn(),
      },
    },
  },
}));

const OFF = { enabled: false, method: null, enrolled_at: null, recovery_codes_remaining: 0 };
const ON = { enabled: true, method: "totp" as const, enrolled_at: "2026-11-21T00:00:00Z", recovery_codes_remaining: 10 };

function renderBlock() {
  return render(<ThemeProvider><TwoStepVerificationBlock /></ThemeProvider>);
}

describe("TwoStepVerificationBlock", () => {
  beforeEach(() => {
    Object.values(api.me.mfa).forEach(fn => vi.mocked(fn).mockReset());
  });

  it("sets up an authenticator, then shows the recovery codes once", async () => {
    vi.mocked(api.me.mfa.status).mockResolvedValueOnce(OFF).mockResolvedValue(ON);
    vi.mocked(api.me.mfa.enroll).mockResolvedValue({
      secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
      otpauth_uri: "otpauth://totp/Aether:a%40co.com?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Aether",
      expires_in_seconds: 900,
    });
    vi.mocked(api.me.mfa.confirm).mockResolvedValue({ enabled: true, recovery_codes: ["aaaa-bbbb", "cccc-dddd"] });
    const user = userEvent.setup();
    renderBlock();

    await user.click(await screen.findByTestId("two-step-enable"));
    expect(await screen.findByAltText("QR code for your authenticator app")).toBeTruthy();
    expect(screen.getByTestId("two-step-secret").textContent).toBe("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP");
    await user.type(screen.getByTestId("two-step-code"), "123456");
    await user.click(screen.getByTestId("two-step-confirm"));

    expect(api.me.mfa.confirm).toHaveBeenCalledWith("123456");
    expect((await screen.findByTestId("two-step-recovery-codes")).textContent).toContain("aaaa-bbbb");
    await user.click(screen.getByTestId("two-step-done"));
    expect(await screen.findByText("On")).toBeTruthy();
  });

  it("needs a code to turn it off", async () => {
    vi.mocked(api.me.mfa.status).mockResolvedValueOnce(ON).mockResolvedValue(OFF);
    vi.mocked(api.me.mfa.disable).mockRejectedValueOnce(new Error("Incorrect code.")).mockResolvedValueOnce({ enabled: false });
    const user = userEvent.setup();
    renderBlock();

    await user.click(await screen.findByTestId("two-step-disable"));
    await user.type(screen.getByTestId("two-step-action-code"), "000000");
    await user.click(screen.getByTestId("two-step-action-confirm"));
    expect(await screen.findByText("Incorrect code.")).toBeTruthy();
    await user.clear(screen.getByTestId("two-step-action-code"));
    await user.type(screen.getByTestId("two-step-action-code"), "111111");
    await user.click(screen.getByTestId("two-step-action-confirm"));
    expect(await screen.findByTestId("two-step-enable")).toBeTruthy();
  });

  it("says plainly when this sign-in cannot manage it", async () => {
    vi.mocked(api.me.mfa.status).mockRejectedValue(new Error("forbidden"));
    renderBlock();
    expect(await screen.findByText("Two-step verification is unavailable for this sign-in.")).toBeTruthy();
  });
});
