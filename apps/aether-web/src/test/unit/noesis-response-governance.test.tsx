import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { NoesisResponsePayload } from "@aether/ui";

const auth = vi.hoisted(() => ({ user: { id: "noesis-governance-test" } }));
const myPermissions = vi.hoisted(() => vi.fn());

vi.mock("@aether-app/features/auth", () => ({ useAuth: () => auth }));
vi.mock("@aether-app/lib/api/endpoints", () => ({
  api: { security: { myPermissions } },
}));

import {
  NoesisResponseGovernance,
  hasDecisionApprovalPermission,
  responseHasGovernedProposal,
} from "@aether-app/features/noesis/noesis-response-governance";

const response: NoesisResponsePayload = {
  answer: "A recommendation is available.",
  mode: "deterministic",
  intent: "recommendation_lookup",
  confidence: 0.9,
  entities: [],
  results: [{ recommendation_id: "rec-1", type: "recommendation" }],
  graph: { nodes: [], edges: [], highlights: [] },
  actions: [],
  warnings: [],
  query_debug: { request_id: "request-1" },
  evidence: {
    sources: [
      {
        service: "intelligence",
        resource_type: "recommendation",
        fetched_at: "2026-09-09T00:00:00Z",
      },
    ],
    claims: [
      {
        claim: "Review this action",
        claim_type: "recommendation",
        confidence: 0.9,
      },
    ],
    sufficient: true,
  },
};

describe("Noesis response governance", () => {
  beforeEach(() => {
    myPermissions.mockReset().mockResolvedValue({
      roles: ["tenant_owner"],
      permissions: [
        {
          permission_id: "perm-1",
          domain: "decisions",
          action: "approve",
          scope: "own_tenant",
        },
      ],
    });
  });

  it("recognizes only explicit decision approval permissions", () => {
    expect(
      hasDecisionApprovalPermission({
        permissions: [{ domain: "decisions", action: "approve" }],
      }),
    ).toBe(true);
    expect(
      hasDecisionApprovalPermission({
        permissions: [{ domain: "decisions", action: "read" }],
      }),
    ).toBe(false);
    expect(
      hasDecisionApprovalPermission({
        permissions: [{ domain: "kyber", action: "approve" }],
      }),
    ).toBe(false);
    expect(hasDecisionApprovalPermission({ permissions: "approve" })).toBe(
      false,
    );
  });

  it("identifies governed recommendations from typed evidence or result identifiers", () => {
    expect(responseHasGovernedProposal(response)).toBe(true);
    expect(
      responseHasGovernedProposal({
        ...response,
        evidence: undefined,
        results: [{ id: "result-1" }],
      }),
    ).toBe(false);
  });

  it("shows trace metadata and routes proposal review without approving or dispatching", async () => {
    render(
      <MemoryRouter>
        <NoesisResponseGovernance response={response} />
      </MemoryRouter>,
    );

    expect(
      screen.getByTestId("noesis-response-governance"),
    ).toBeInTheDocument();
    expect(screen.getByText("Trace available")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText("Approval permission resolved"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Review in Decision Intelligence" }),
    ).toBeInTheDocument();
    expect(myPermissions).toHaveBeenCalledTimes(1);
  });
});
