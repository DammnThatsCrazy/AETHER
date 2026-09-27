/**
 * A new account arrives from the pricing page (through Auth0 sign-up) on
 * /billing?plan=<id>. The page starts that plan's Stripe checkout once, and
 * lists only the self-serve plans, in price order.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ThemeProvider, ToastProvider } from "@aether/ui";
import { BillingPage } from "./billing-page";

const state = vi.hoisted(() => ({
  capability: "available" as string,
  currentPlan: "alpha",
  annualPlans: [] as string[],
  createCheckout: vi.fn(async (_args: { planTier: string; interval?: string }) => ({
    url: "https://checkout.stripe.test/s",
  })),
}));

function plan(plan_id: string, price: number, contact_sales = false) {
  return {
    plan_id,
    display_name: plan_id[0]!.toUpperCase() + plan_id.slice(1),
    price_monthly: price,
    currency: "USD",
    contact_sales,
    included_usage: 1000,
    rate_limit_rpm: 60,
    monthly_quota: 1000,
    burst_rpm: 60,
    service_count: 1,
    target_user: "team",
  };
}

vi.mock("@aether-app/features/account", () => ({
  useBillingPlans: () => ({
    data: [
      plan("omega", 0, true),
      plan("delta", 1999),
      plan("alpha", 0),
      plan("gamma", 999),
      plan("beta", 199),
      plan("epsilon", 0, true),
    ],
    isLoading: false,
    error: null,
  }),
  useBillingCapability: () => ({ data: { status: state.capability, annual_plans: state.annualPlans } }),
  useMeProfile: () => ({
    data: { name: "Ada", contact_email: "ada@example.com", plan: { plan_id: state.currentPlan } },
  }),
  useInvoices: () => ({ data: [], isLoading: false, error: null }),
  useCreateCheckout: () => ({ mutate: state.createCheckout, isLoading: false }),
  useBillingPortal: () => ({ mutate: vi.fn(), isLoading: false }),
  useEnterpriseContact: () => ({ mutate: vi.fn(), isLoading: false }),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderBilling(entry: string) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]}>
          <BillingPage />
          <LocationProbe />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe("BillingPage plan hand-off", () => {
  beforeEach(() => {
    state.capability = "available";
    state.currentPlan = "alpha";
    state.createCheckout.mockClear();
    state.annualPlans = [];
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, href: "http://localhost/billing" },
    });
  });

  it("starts checkout for the plan chosen on the pricing page, once", async () => {
    const { rerender } = renderBilling("/billing?plan=beta");

    await waitFor(() => expect(state.createCheckout).toHaveBeenCalledWith({ planTier: "beta", interval: "monthly" }));
    rerender(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/billing?plan=beta"]}>
            <BillingPage />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
    await waitFor(() => expect(window.location.href).toBe("https://checkout.stripe.test/s"));
    expect(state.createCheckout).toHaveBeenCalledTimes(1);
  });

  it("consumes the hand-off, so Back from Stripe or a reload does not start another checkout", async () => {
    renderBilling("/billing?plan=beta");
    await waitFor(() => expect(state.createCheckout).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("location").textContent).toBe("/billing");
  });

  it("does not start checkout for the free plan, the current plan, or an unknown plan", async () => {
    renderBilling("/billing?plan=alpha");
    state.currentPlan = "gamma";
    renderBilling("/billing?plan=gamma");
    renderBilling("/billing?plan=omega");
    await new Promise(resolve => setTimeout(resolve, 20));
    expect(state.createCheckout).not.toHaveBeenCalled();
  });

  it("does not start checkout while billing is unavailable", async () => {
    state.capability = "unavailable";
    renderBilling("/billing?plan=delta");
    await new Promise(resolve => setTimeout(resolve, 20));
    expect(state.createCheckout).not.toHaveBeenCalled();
  });

  it("uses the yearly price when the pricing page chose annual and it is offered", async () => {
    state.annualPlans = ["beta", "gamma"];
    renderBilling("/billing?plan=gamma&interval=annual");
    await waitFor(() =>
      expect(state.createCheckout).toHaveBeenCalledWith({ planTier: "gamma", interval: "annual" }),
    );
  });

  it("falls back to monthly, and says so, when the plan has no yearly price", async () => {
    state.annualPlans = ["beta"];
    renderBilling("/billing?plan=delta&interval=annual");
    await waitFor(() =>
      expect(state.createCheckout).toHaveBeenCalledWith({ planTier: "delta", interval: "monthly" }),
    );
    expect(await screen.findByText(/Annual billing is not available for this plan yet/)).toBeTruthy();
  });

  it("lists only the self-serve plans, in price order", () => {
    renderBilling("/billing");
    const names = ["Alpha", "Beta", "Gamma", "Delta"].map(name => screen.getByText(name));
    for (let i = 1; i < names.length; i += 1) {
      expect(
        names[i - 1]!.compareDocumentPosition(names[i]!) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
    expect(screen.queryByText("Omega")).toBeNull();
    expect(screen.queryByText("Epsilon")).toBeNull();
  });
});
