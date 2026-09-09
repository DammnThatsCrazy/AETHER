import { describe, expect, it } from "vitest";
import type { GraphScope } from "@aether/shared/graph-context-contract";
import {
  graphObjectRef,
  normalizeEvidence,
  temporalForWindow,
  withGraphContext,
  withGraphFocus,
} from "@kyber/features/profile360/profile360-context";

const scope: GraphScope = {
  tenant_id: "tenant-a",
  workspace_id: "workspace-a",
  environment_id: "staging",
};

describe("Profile360 graph context bridge", () => {
  it("creates tenant and environment-bound object references", () => {
    expect(graphObjectRef(scope, { id: "wallet-1", type: "wallet" })).toEqual({
      tenant_id: "tenant-a",
      environment_id: "staging",
      kind: "wallet",
      id: "wallet-1",
    });
  });

  it("preserves canonical context while adding an opaque focus token", () => {
    const base = withGraphContext(
      "/profile360/human/entity-1",
      "tmode=window&tz=UTC",
    );
    expect(base).toBe("/profile360/human/entity-1?tmode=window&tz=UTC");
    expect(
      withGraphFocus(
        base,
        graphObjectRef(scope, { id: "wallet-1", type: "wallet" }),
      ),
    ).toBe(
      "/profile360/human/entity-1?tmode=window&tz=UTC&focus=wallet%3Awallet-1",
    );
  });

  it("drops evidence records that lack a durable identity or source", () => {
    expect(
      normalizeEvidence([
        {
          id: "event-1",
          type: "event",
          source: "segment",
          observed_at: "2026-09-09T12:00:00Z",
        },
        { id: "not-enough" },
      ]),
    ).toEqual([
      {
        id: "event-1",
        type: "event",
        source: "segment",
        observedAt: "2026-09-09T12:00:00Z",
      },
    ]);
  });

  it("produces a bounded UTC range for the selected window", () => {
    const now = new Date("2026-09-09T12:00:00.000Z");
    const temporal = temporalForWindow("30d", now);
    expect(temporal.mode).toBe("window");
    expect(temporal.range).toEqual({
      kind: "instant",
      start: "2026-08-10T12:00:00.000Z",
      endExclusive: "2026-09-09T12:00:00.000Z",
    });
  });
});
