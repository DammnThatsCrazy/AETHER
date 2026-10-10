import { describe, expect, it } from "vitest";
import { MarkdownReportGenerator } from "./markdown";
import { JsonReportGenerator } from "./json";
import type { ProofResult } from "@aether/proof-runner";

const result: ProofResult = {
  proofId: "identity-continuity-gate-7",
  status: "failed",
  startedAt: "2026-09-27T12:00:00.000Z",
  completedAt: "2026-09-27T12:00:03.000Z",
  totalDurationMs: 3000,
  summary: "One proof check failed.",
  steps: [
    {
      stepId: "contract-check",
      status: "passed",
      durationMs: 1200,
      reason: "Generated twins are current",
    },
    {
      stepId: "identity-suite",
      status: "failed",
      durationMs: 1800,
      reason: "Expected 1 | got 0\ninspect fixture",
    },
  ],
};

describe("proof report generators", () => {
  it("renders a Markdown table with escaped, newline-safe evidence", () => {
    const report = new MarkdownReportGenerator().generate(result);

    expect(report).toContain("# Proof Report: identity-continuity-gate-7");
    expect(report).toContain("**Status:** `failed`");
    expect(report).toContain("| Result | Step | Status | Duration | Reason |");
    expect(report).toContain("| ✅ | `contract-check` | passed | 1200ms | Generated twins are current |");
    expect(report).toContain("| ❌ | `identity-suite` | failed | 1800ms | Expected 1 \\| got 0 inspect fixture |");
  });

  it("renders structured JSON with the actual proof and step statuses", () => {
    const report = JSON.parse(new JsonReportGenerator().generate(result));

    expect(report.proof).toMatchObject({
      proof_id: "identity-continuity-gate-7",
      status: "failed",
      total_duration_ms: 3000,
    });
    expect(report.steps).toEqual([
      expect.objectContaining({ step_id: "contract-check", status: "passed" }),
      expect.objectContaining({ step_id: "identity-suite", status: "failed" }),
    ]);
  });
});
