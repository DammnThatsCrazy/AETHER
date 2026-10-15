// @aether/proof-runner — 24-line report generation (blueprint spec section 19)
import type { ProofStepResult } from "./runner";

/** Ordered list of the 24 report line labels (blueprint spec section 19). */
export const REPORT_LINES = [
  "Tenant provisioning",
  "Workspace provisioning",
  "Platform registration",
  "SDK key generation",
  "SDK heartbeat",
  "Web event ingestion",
  "Identify event ingestion",
  "Conversion ingestion",
  "Connector fixture import",
  "Webhook replay",
  "Raw evidence storage",
  "Normalization",
  "Identity resolution",
  "Profile write",
  "Journey write",
  "Campaign resolution",
  "Value attachment",
  "Graph node write",
  "Graph edge write",
  "Profile 360 query",
  "Campaign 360 query",
  "Communications 360 query",
  "Lens activation",
  "Explanation / provenance",
];

/** Map a step function name → report label */
const STEP_NAME_TO_LABEL: Record<string, string> = {
  tenantProvisioning: "Tenant provisioning",
  workspaceProvisioning: "Workspace provisioning",
  platformRegistration: "Platform registration",
  sdkKeyGeneration: "SDK key generation",
  sdkHeartbeat: "SDK heartbeat",
  webEventIngestion: "Web event ingestion",
  identifyEventIngestion: "Identify event ingestion",
  conversionIngestion: "Conversion ingestion",
  connectorFixtureImport: "Connector fixture import",
  webhookReplay: "Webhook replay",
  rawEvidenceStorage: "Raw evidence storage",
  normalization: "Normalization",
  identityResolution: "Identity resolution",
  profileWrite: "Profile write",
  journeyWrite: "Journey write",
  campaignResolution: "Campaign resolution",
  valueAttachment: "Value attachment",
  graphNodeWrite: "Graph node write",
  graphEdgeWrite: "Graph edge write",
  profile360Query: "Profile 360 query",
  campaign360Query: "Campaign 360 query",
  communications360Query: "Communications 360 query",
  lensActivation: "Lens activation",
  explanationProvenance: "Explanation / provenance",
};

// ---------------------------------------------------------------------------
// Line renderer
// ---------------------------------------------------------------------------

/** Render a single report line for one step result.
 *
 * Format (markdown, aligned):
 *   - `✓` PASS  label
 *   - `✗` FAIL  label — reason
 *   - `○` SKIP  label — reason
 *   - `✗` ERROR label — reason
 */
export function renderReportLine(
  stepResult: ProofStepResult,
): string {
  const label = STEP_NAME_TO_LABEL[stepResult.stepId] ?? stepResult.stepId;
  const status = stepResult.status;
  const icon =
    status === "passed"
      ? "✓"
      : status === "skipped"
      ? "○"
      : "✗";
  const reason =
    stepResult.reason && stepResult.status !== "passed"
      ? ` — ${stepResult.reason}`
      : stepResult.reason
      ? ` — ${stepResult.reason}`
      : "";
  return `${icon}  ${status.toUpperCase()}  ${label}${reason}`;
}

// ---------------------------------------------------------------------------
// Full report generation
// ---------------------------------------------------------------------------

/** Generate the 24-line pass/fail report string (blueprint spec section 19). */
export function generateReport(
  results: ProofStepResult[],
  options?: { title?: string; generatedAt?: string },
): string {
  const lines: string[] = [];
  if (options?.title) {
    lines.push(`# ${options.title}`);
    lines.push("");
  }
  lines.push("## Proof Results");
  lines.push("");

  // Header row
  const statusIcon = { passed: "✓", failed: "✗", skipped: "○", error: "✗" };
  const statusColWidth = 6;
  const nameColWidth = REPORT_LINES.reduce((acc, lbl) => Math.max(acc, lbl.length), 0);
  lines.push(
    `${"Step".padEnd(nameColWidth + 2)}| ${"Status".padEnd(statusColWidth)} | Details`,
  );
  lines.push("-".repeat(nameColWidth + 2 + statusColWidth + 6));
  lines.push("");

  for (let i = 0; i < REPORT_LINES.length; i++) {
    const label = REPORT_LINES[i];
    const result = results.find((r) => STEP_NAME_TO_LABEL[r.stepId] === label);
    const status = result?.status ?? "skipped";
    const reason =
      result?.reason && status !== "passed" ? ` — ${result.reason}` : "";
    const icon = statusIcon[status] ?? "?";
    const detail = reason || (status === "passed" ? "Passed" : "No data");
    lines.push(
      `${icon} ${label.padEnd(nameColWidth)} | ${status.padEnd(statusColWidth)} | ${detail}`,
    );
  }

  lines.push("");
  const passed = results.filter((r) => r.status === "passed").length;
  const failed = results.filter((r) => r.status === "failed").length;
  const skipped = results.filter((r) => r.status === "skipped").length;
  const errors = results.filter((r) => r.status === "error").length;
  lines.push("");
  lines.push("## Summary");
  lines.push("");
  lines.push(`- **Total:** ${REPORT_LINES.length}`);
  lines.push(`- **Passed:** ${passed}`);
  lines.push(`- **Failed:** ${failed}`);
  lines.push(`- **Skipped:** ${skipped}`);
  lines.push(`- **Errors:** ${errors}`);
  lines.push("");
  if (options?.generatedAt) {
    lines.push(`_Generated: ${options.generatedAt}_`);
  }

  return lines.join("\n");
}

/** Generate a minimal 24-line markdown report (one line per step). */
export function generateMinimalReport(results: ProofStepResult[]): string {
  const lines: string[] = [];
  lines.push("# Aether Functionality Proof — Results");
  lines.push("");
  for (let i = 0; i < REPORT_LINES.length; i++) {
    const label = REPORT_LINES[i];
    const result = results.find((r) => STEP_NAME_TO_LABEL[r.stepId] === label);
    if (result) {
      lines.push(renderReportLine(result));
    } else {
      lines.push(`○  SKIPPED  ${label} — not executed`);
    }
  }
  lines.push("");
  const passed = results.filter((r) => r.status === "passed").length;
  lines.push(`\nSummary: ${passed}/${REPORT_LINES.length} passed`);
  return lines.join("\n");
}
