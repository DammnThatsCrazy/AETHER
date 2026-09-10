/**
 * WS-3 activation deep-link prefill (tenant-side consumer of the marketing
 * /activate handoff). When /activate (or /activation) carries
 * `?experience=advertising_campaigns&intent=connect` (or a goals-first
 * `?intent=<goal_token>`), ActivatePage applies a ONE-TIME DRAFT preselect —
 * chips are checked but nothing is ever auto-saved. Existing durable goals win,
 * junk params are ignored, and a matching recommended-plan category block is
 * transiently focused (data-handoff-focus + ring), mirroring the Settings row
 * handoff behavior.
 *
 * Mock surface mirrors activate-page-route-state.test.tsx (the full hook set
 * ActivatePage and its reused ./activation-page steps consume).
 */
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@aether/ui";
import { ActivatePage } from "@aether-app/pages/activation/activate-page";

const state = vi.hoisted(() => ({
  status: {} as Record<string, unknown>,
  catalog: {} as Record<string, unknown>,
  plan: {} as Record<string, unknown>,
  mutation: {} as Record<string, unknown>,
  firstValue: {} as Record<string, unknown>,
  createKeys: {} as Record<string, unknown>,
  sendEvent: {} as Record<string, unknown>,
}));

const NOT_STARTED = {
  state: "not_started",
  selected_plan_tier: null,
  sdk_selection: [],
  created_key_ids: [],
  billing_state: "billing_pending",
  first_value_evidence: {},
  waiting_reason: null,
  history: [],
};

/** Catalog options: tokens + the experiences they recommend (single source). */
const INTENTS = [
  {
    token: "run_advertising",
    label: "Run advertising",
    description: "Launch and measure ad campaigns",
    recommended_categories: ["advertising_campaigns"],
  },
  {
    token: "grow_revenue",
    label: "Grow revenue",
    description: "Expand recurring revenue",
    recommended_categories: ["commerce_revenue", "crm_customer"],
  },
  {
    token: "know_customers",
    label: "Know customers",
    description: "Understand who buys from you",
    recommended_categories: ["analytics_behavior", "crm_customer"],
  },
];

const AD_CATEGORY = {
  experience_category: "advertising_campaigns",
  display_name: "Advertising",
  recommended_by_intents: ["run_advertising"],
  connected_count: 0,
  integration_count: 0,
  integrations: [],
};

vi.mock("@aether-app/features/activation/use-activation", () => ({
  ACTIVATION_PLAN_TIERS: ["P1", "P2", "P3", "P4"],
  activationStateLabel: (s: string) => s,
  activationNextAction: (s: string) => `next: ${s}`,
  activationCapabilityState: () => "provisioning",
  useActivationStatus: () => state.status,
  useSelectPlan: () => state.mutation,
  useSelectSdks: () => state.mutation,
  useCreateSdkKeys: () => state.createKeys,
  useSendTestEvent: () => state.sendEvent,
  useFirstValue: () => state.firstValue,
  useCompleteActivation: () => state.mutation,
}));

vi.mock("@aether-app/features/activation/use-tenant-readiness", () => ({
  useTenantReadiness: () => ({
    data: undefined,
    isLoading: false,
    error: null,
  }),
  deriveGraphMaturity: () => ({ state: "no_data", blocking: [] }),
}));

vi.mock("@aether-app/features/activation/use-activation-intents", () => ({
  useActivationIntentsCatalog: () => state.catalog,
  useActivationPlan: () => state.plan,
  useActivationConnectAction: () => state.mutation,
  useSaveActivationIntents: () => state.mutation,
}));

const originalScrollIntoView = Element.prototype.scrollIntoView;

function renderActivateAt(initialEntry: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ActivatePage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

/** durable = empty, plan settled, catalog loaded. */
function setEmptyDurable() {
  state.status = {
    data: NOT_STARTED,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  };
  state.catalog = {
    data: { intents: INTENTS },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  };
  state.plan = {
    data: {
      tenant_id: "t1",
      needs_selection: true,
      selected_intents: [],
      categories: [],
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  };
}

function chip(token: string) {
  return document.querySelector(`[data-activation-intent="${token}"]`);
}

describe("ActivatePage activation deep-link prefill", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    state.status = {
      data: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.catalog = {
      data: { intents: [] },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.plan = {
      data: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.mutation = {
      mutate: vi.fn(),
      isLoading: false,
      error: null,
      data: null,
      reset: vi.fn(),
    };
    state.firstValue = {
      data: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.createKeys = {
      mutate: vi.fn(),
      isLoading: false,
      error: null,
      data: null,
      reset: vi.fn(),
    };
    state.sendEvent = {
      mutate: vi.fn(),
      isLoading: false,
      error: null,
      data: null,
      reset: vi.fn(),
    };
  });

  afterAll(() => {
    Element.prototype.scrollIntoView = originalScrollIntoView;
  });

  it("preselects the chip named by ?intent as a draft once the catalog loads (durable empty)", () => {
    setEmptyDurable();
    renderActivateAt("/activation?intent=run_advertising");

    expect(chip("run_advertising")).toHaveAttribute("aria-pressed", "true");
    expect(chip("grow_revenue")).toHaveAttribute("aria-pressed", "false");
    expect(chip("know_customers")).toHaveAttribute("aria-pressed", "false");
  });

  it("preselects every chip whose recommended_categories include the ?experience", () => {
    setEmptyDurable();
    renderActivateAt(
      "/activation?experience=advertising_campaigns&intent=connect",
    );

    expect(chip("run_advertising")).toHaveAttribute("aria-pressed", "true");
    expect(chip("grow_revenue")).toHaveAttribute("aria-pressed", "false");
    expect(chip("know_customers")).toHaveAttribute("aria-pressed", "false");
  });

  it("ignores junk ?intent / ?experience params (nothing preselected)", () => {
    setEmptyDurable();
    renderActivateAt("/activation?intent=garbage&experience=not_a_category");

    expect(chip("run_advertising")).toHaveAttribute("aria-pressed", "false");
    expect(chip("grow_revenue")).toHaveAttribute("aria-pressed", "false");
    expect(chip("know_customers")).toHaveAttribute("aria-pressed", "false");
  });

  it("never calls the save mutation on a mere landing", () => {
    setEmptyDurable();
    renderActivateAt(
      "/activation?intent=run_advertising&experience=advertising_campaigns",
    );

    expect(chip("run_advertising")).toHaveAttribute("aria-pressed", "true");
    expect(state.mutation.mutate).not.toHaveBeenCalled();
  });

  it("never overrides an existing durable selection with handoff params", () => {
    state.status = {
      data: NOT_STARTED,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.catalog = {
      data: { intents: INTENTS },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.plan = {
      data: {
        tenant_id: "t1",
        needs_selection: false,
        selected_intents: ["grow_revenue"],
        categories: [],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderActivateAt(
      "/activation?intent=run_advertising&experience=advertising_campaigns",
    );

    expect(chip("grow_revenue")).toHaveAttribute("aria-pressed", "true");
    expect(chip("run_advertising")).toHaveAttribute("aria-pressed", "false");
    expect(chip("know_customers")).toHaveAttribute("aria-pressed", "false");
  });

  it("focuses the matching recommended-plan block for a requested ?experience when a plan exists", () => {
    state.status = {
      data: NOT_STARTED,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.catalog = {
      data: { intents: INTENTS },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.plan = {
      data: {
        tenant_id: "t1",
        needs_selection: false,
        selected_intents: ["run_advertising"],
        categories: [AD_CATEGORY],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderActivateAt("/activation?experience=advertising_campaigns");

    const block = document.querySelector(
      '[data-plan-category="advertising_campaigns"]',
    );
    expect(block).not.toBeNull();
    expect(block).toHaveAttribute("data-handoff-focus", "true");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({
      block: "center",
      behavior: "smooth",
    });
    // Plan category is visible copy for the matched experience.
    expect(screen.getByText("Advertising")).toBeInTheDocument();
  });

  it("is inert when the activation URL carries no handoff params", () => {
    setEmptyDurable();
    renderActivateAt("/activation");

    expect(chip("run_advertising")).toHaveAttribute("aria-pressed", "false");
    expect(document.querySelector('[data-handoff-focus="true"]')).toBeNull();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    expect(state.mutation.mutate).not.toHaveBeenCalled();
  });

  it("offers the graph workspace only when backend activation is exactly complete", () => {
    setEmptyDurable();
    state.status.data = { ...NOT_STARTED, state: "complete" };
    renderActivateAt("/activation");

    const handoff = screen.getByTestId("activation-explore-handoff");
    expect(handoff).toHaveAttribute("href", "/explore");
    expect(handoff).toHaveTextContent("Your graph workspace is available");
  });

  it("does not claim graph readiness for a non-complete activation state", () => {
    setEmptyDurable();
    state.status.data = { ...NOT_STARTED, state: "first_value_ready" };
    renderActivateAt("/activation");

    expect(screen.queryByTestId("activation-explore-handoff")).toBeNull();
    expect(screen.queryByText(/graph workspace is available/i)).toBeNull();
  });
});
