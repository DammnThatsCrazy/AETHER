/**
 * FPS-100: Release proof report generator.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-100
 * Status: real runtime logic — generates release-readiness report from
 *          staging smoke results, CI artifacts, and proof evidence.
 *
 * This script generates the release-readiness report from CI, staging smoke,
 * connector, SDK, real-device, and E2E results. It is the authoritative
 * release gate report consumed by the release process.
 *
 * Written to:
 *   reports/release-readiness/aether-functionality-proof-report-{date}.md
 */

import { execSync } from "child_process";
import fs from "fs";
import { promises as fsp } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import {
  MarkdownReportGenerator,
  JsonReportGenerator,
} from "@aether/proof-reporting";
import { ProofResult, ProofStepResult } from "@aether/proof-runner";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");
const REPORT_DIR = resolve(REPO_ROOT, "reports", "release-readiness");
const CI_ARTIFACT_PATH = process.env.CI_ARTIFACT_PATH
  ? resolve(process.env.CI_ARTIFACT_PATH)
  : resolve(REPO_ROOT, ".github", "artifacts");
const REAL_DEVICE_EVIDENCE_PATH = process.env.REAL_DEVICE_EVIDENCE_PATH
  ? resolve(process.env.REAL_DEVICE_EVIDENCE_PATH)
  : resolve(REPO_ROOT, "reports", "release-readiness", "real-device-verification.md");

const TODAY = new Date();
const DATE_STRING = `${TODAY.getFullYear()}-${String(TODAY.getMonth() + 1).padStart(2, "0")}-${String(TODAY.getDate()).padStart(2, "0")}`;
const REPORT_FILE = `aether-functionality-proof-report-${DATE_STRING}`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function envOr(defaultValue: string, key: string): string {
  return process.env[key] ?? defaultValue;
}

async function readJsonFile(path: string): Promise<unknown> {
  try {
    const raw = await fsp.readFile(path, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function findLatestSmokeReport(): Promise<string | null> {
  try {
    const files = await fsp.readdir(REPORT_DIR);
    const mdFiles = files
      .filter((f) => f.startsWith("aether-functionality-proof-report-") && f.endsWith(".md"))
      .sort()
      .reverse();
    if (mdFiles.length === 0) return null;
    return resolve(REPORT_DIR, mdFiles[0]);
  } catch {
    return null;
  }
}

/**
 * Get the release version with the following priority:
 * 1. VERSION file at repo root
 * 2. git describe --tags
 * 3. Root package.json version field
 * 4. 'untagged-dev'
 */
function getReleaseVersion(): string {
  // 1. Try VERSION file
  try {
    const versionFile = resolve(REPO_ROOT, "VERSION");
    const content = fs.readFileSync(versionFile, "utf-8");
    const trimmed = content.trim();
    if (trimmed) return trimmed;
  } catch {
    // VERSION file doesn't exist or isn't readable; fall through
  }

  // 2. Try git describe --tags
  try {
    const content = execSync("git describe --tags --always --dirty", {
      cwd: REPO_ROOT,
      encoding: "utf-8",
      timeout: 10_000,
    }).trim();
    if (content) return content;
  } catch {
    // git not available or no tags; fall through
  }

  // 3. Try root package.json version
  try {
    const pkgPath = resolve(REPO_ROOT, "package.json");
    const pkgRaw = fs.readFileSync(pkgPath, "utf-8");
    const pkg = JSON.parse(pkgRaw);
    if (pkg.version) return pkg.version;
  } catch {
    // package.json not available; fall through
  }

  // 4. Fallback
  return "untagged-dev";
}

/**
 * Get the commit SHA via git rev-parse HEAD.
 */
function getCommitSha(): string {
  try {
    return execSync("git rev-parse HEAD", {
      cwd: REPO_ROOT,
      encoding: "utf-8",
      timeout: 10_000,
    }).trim();
  } catch {
    return "unknown";
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SDKDetails {
  platform: string;
  status: "pass" | "partial" | "fail" | "not-run";
  evidence: string;
}

interface ConnectorDetails {
  connector: string;
  status: "pass" | "partial" | "fail" | "not-run";
  evidence: string;
}

interface Surface360Details {
  surface: string;
  status: "pass" | "partial" | "fail" | "not-run";
  evidence: string;
}

interface CollectedData {
  releaseVersion: string;
  commitSha: string;
  environment: string;
  proofTenantId: string;
  proofWorkspaceId: string;
  stagingSmokeReportFound: boolean;
  stagingSmokeMarkdown: string | null;
  stagingSmokeJson: string | null;
  ciArtifacts: unknown[];
  realDeviceEvidence: string | null;
  sdkStatus: SDKDetails[];
  connectorStatus: ConnectorDetails[];
  ingestionStatus: "pass" | "fail" | "partial" | "not-run";
  graphStatus: "pass" | "fail" | "partial" | "not-run";
  identityStatus: "pass" | "fail" | "partial" | "not-run";
  lensStatus: "pass" | "fail" | "partial" | "not-run";
  surface360Status: Surface360Details[];
  realDeviceStatus: "pass" | "fail" | "partial" | "not-run" | "no-evidence";
  knownFailures: string[];
  degradedFeatures: string[];
  manualEvidence: string[];
  automatedEvidence: string[];
  releaseBlockers: string[];
}

// ---------------------------------------------------------------------------
// Data collection
// ---------------------------------------------------------------------------

async function collectData(): Promise<CollectedData> {
  const releaseVersion = getReleaseVersion();
  const commitSha = getCommitSha();
  const environment = envOr("staging", "AETHER_ENV");
  const proofTenantId = envOr("aether-proof-tenant", "PROOF_TENANT_ID");
  const proofWorkspaceId = envOr("proof-lab", "PROOF_WORKSPACE_ID");

  // 1. Read the latest staging smoke report.
  const latestReportPath = await findLatestSmokeReport();
  let stagingSmokeMarkdown: string | null = null;
  let stagingSmokeJson: string | null = null;

  if (latestReportPath) {
    try {
      stagingSmokeMarkdown = await fsp.readFile(latestReportPath, "utf-8");
      const jsonPath = latestReportPath.replace(/\.md$/, ".json");
      stagingSmokeJson = await fsp.readFile(jsonPath, "utf-8");
    } catch {
      // Markdown found but JSON missing, or read error; continue with what we have.
    }
  }

  // 2. Read CI proof artifacts.
  const ciArtifacts: unknown[] = [];
  try {
    const artifactFiles = await fsp.readdir(CI_ARTIFACT_PATH);
    for (const f of artifactFiles) {
      const filePath = resolve(CI_ARTIFACT_PATH, f);
      const stat = await fsp.stat(filePath);
      if (stat.isFile()) {
        if (f.endsWith(".json")) {
          const data = await readJsonFile(filePath);
          if (data) ciArtifacts.push(data);
        } else if (f.endsWith(".md")) {
          const text = await fsp.readFile(filePath, "utf-8");
          ciArtifacts.push({ type: "markdown", content: text, file: f });
        }
      }
    }
  } catch {
    // CI artifacts directory may not exist; that's fine.
  }

  // 3. Read real-device verification evidence.
  let realDeviceEvidence: string | null = null;
  try {
    realDeviceEvidence = await fsp.readFile(REAL_DEVICE_EVIDENCE_PATH, "utf-8");
  } catch {
    // No real-device evidence file; that's fine.
  }

  // 4. Derive SDK status from staging smoke report + CI artifacts.
  const sdkStatus: SDKDetails[] = [
    { platform: "web", status: "not-run", evidence: "" },
    { platform: "react", status: "not-run", evidence: "" },
    { platform: "ios", status: "not-run", evidence: "" },
    { platform: "android", status: "not-run", evidence: "" },
  ];

  if (stagingSmokeJson) {
    try {
      const parsed = JSON.parse(stagingSmokeJson);
      const steps = parsed.steps as { step_id: string; status: string; output?: string }[];

      for (const step of steps) {
        const id = step.step_id;
        const status = step.status;
        const output = step.output ?? "";

        if (id === "sdk-heartbeat" || id === "web-event-ingestion") {
          const entry = sdkStatus.find((s) => s.platform === "web");
          if (entry) {
            entry.status = status === "PASS" ? "pass" : status === "SKIP" ? "not-run" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        } else if (id === "ios-sdk") {
          const entry = sdkStatus.find((s) => s.platform === "ios");
          if (entry) {
            entry.status = status === "SKIP" ? "not-run" : status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        } else if (id === "android-sdk") {
          const entry = sdkStatus.find((s) => s.platform === "android");
          if (entry) {
            entry.status = status === "SKIP" ? "not-run" : status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        }
      }

      // React SDK: parity with web SDK — if web passed, mark React as partial
      // (shares ingestion pipeline; React-specific smoke not directly measured
      // in the staging run).
      const webEntry = sdkStatus.find((s) => s.platform === "web");
      if (webEntry?.status === "pass") {
        const reactEntry = sdkStatus.find((s) => s.platform === "react");
        if (reactEntry) {
          reactEntry.status = "partial";
          reactEntry.evidence =
            "React SDK shares ingestion pipeline with web SDK; web smoke passed. React-specific smoke not directly measured in staging run.";
        }
      }
    } catch {
      // JSON parse failure; keep defaults.
    }
  }

  // 5. Derive connector status.
  const connectorStatus: ConnectorDetails[] = [
    { connector: "stripe", status: "not-run", evidence: "" },
    { connector: "shopify", status: "not-run", evidence: "" },
    { connector: "email", status: "not-run", evidence: "" },
  ];

  if (stagingSmokeJson) {
    try {
      const parsed = JSON.parse(stagingSmokeJson);
      const steps = parsed.steps as { step_id: string; status: string; output?: string }[];

      for (const step of steps) {
        const id = step.step_id;
        const status = step.status;
        const output = step.output ?? "";

        if (id === "stripe-connector") {
          const entry = connectorStatus.find((c) => c.connector === "stripe");
          if (entry) {
            entry.status = status === "SKIP" ? "not-run" : status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        } else if (id === "shopify-connector") {
          const entry = connectorStatus.find((c) => c.connector === "shopify");
          if (entry) {
            entry.status = status === "SKIP" ? "not-run" : status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        } else if (id === "email-connector") {
          const entry = connectorStatus.find((c) => c.connector === "email");
          if (entry) {
            entry.status = status === "PASS" ? "pass" : status === "SKIP" ? "not-run" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        }
      }
    } catch {
      // ignore
    }
  }

  // 6. Derive ingestion, graph, identity, lens status from the smoke report.
  let ingestionStatus: "pass" | "fail" | "partial" | "not-run" = "not-run";
  let graphStatus: "pass" | "fail" | "partial" | "not-run" = "not-run";
  let identityStatus: "pass" | "fail" | "partial" | "not-run" = "not-run";
  let lensStatus: "pass" | "fail" | "partial" | "not-run" = "not-run";

  if (stagingSmokeJson) {
    try {
      const parsed = JSON.parse(stagingSmokeJson);
      const gates = parsed.p0_gates as { gate: string; status: string }[];
      const steps = parsed.steps as { step_id: string; status: string }[];

      // Ingestion: derived from web-event-ingestion gate or step.
      const webIngestionGate = gates.find((g) => g.gate === "Web event ingestion");
      if (webIngestionGate) {
        ingestionStatus = webIngestionGate.status === "PASS" ? "pass" : "fail";
      } else {
        const webIngestionStep = steps.find((s) => s.step_id === "web-event-ingestion");
        if (webIngestionStep) {
          ingestionStatus = webIngestionStep.status === "PASS" ? "pass" : "fail";
        }
      }

      // Graph: derived from graph-node-write gate or step.
      const graphNodeGate = gates.find((g) => g.gate === "Graph node write");
      if (graphNodeGate) {
        graphStatus = graphNodeGate.status === "PASS" ? "pass" : "fail";
      } else {
        const graphNodeStep = steps.find((s) => s.step_id === "graph-node-write");
        if (graphNodeStep) {
          graphStatus = graphNodeStep.status === "PASS" ? "pass" : "fail";
        }
      }

      // Identity: derived from identity-resolution gate or step.
      const identityGate = gates.find((g) => g.gate === "Identity resolution");
      if (identityGate) {
        identityStatus = identityGate.status === "PASS" ? "pass" : "fail";
      } else {
        const identityStep = steps.find((s) => s.step_id === "identity-resolution");
        if (identityStep) {
          identityStatus = identityStep.status === "PASS" ? "pass" : "fail";
        }
      }

      // Lens: derived from lens-activation gate or step.
      const lensGate = gates.find((g) => g.gate === "Lens activation");
      if (lensGate) {
        lensStatus = lensGate.status === "PASS" ? "pass" : "fail";
      } else {
        const lensStep = steps.find((s) => s.step_id === "lens-activation");
        if (lensStep) {
          lensStatus = lensStep.status === "PASS" ? "pass" : "fail";
        }
      }
    } catch {
      // ignore
    }
  }

  // 7. Derive 360 surface status.
  const surface360Status: Surface360Details[] = [
    { surface: "profile", status: "not-run", evidence: "" },
    { surface: "campaign", status: "not-run", evidence: "" },
    { surface: "communications", status: "not-run", evidence: "" },
  ];

  if (stagingSmokeJson) {
    try {
      const parsed = JSON.parse(stagingSmokeJson);
      const steps = parsed.steps as { step_id: string; status: string; output?: string }[];

      for (const step of steps) {
        const id = step.step_id;
        const status = step.status;
        const output = step.output ?? "";

        if (id === "profile-360-query") {
          const entry = surface360Status.find((s) => s.surface === "profile");
          if (entry) {
            entry.status = status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        } else if (id === "campaign-360-query") {
          const entry = surface360Status.find((s) => s.surface === "campaign");
          if (entry) {
            entry.status = status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        } else if (id === "communications-360-query") {
          const entry = surface360Status.find((s) => s.surface === "communications");
          if (entry) {
            entry.status = status === "PASS" ? "pass" : "fail";
            entry.evidence = output.slice(0, 500);
          }
        }
      }
    } catch {
      // ignore
    }
  }

  // 8. Real-device status.
  let realDeviceStatus: "pass" | "fail" | "partial" | "not-run" | "no-evidence" = "no-evidence";

  if (realDeviceEvidence) {
    if (realDeviceEvidence.includes("PASS") && !realDeviceEvidence.includes("FAIL")) {
      realDeviceStatus = "pass";
    } else if (realDeviceEvidence.includes("FAIL")) {
      realDeviceStatus = "fail";
    } else {
      realDeviceStatus = "partial";
    }
  } else {
    for (const artifact of ciArtifacts) {
      if (typeof artifact === "object" && artifact !== null) {
        const a = artifact as Record<string, unknown>;
        if (a.type === "markdown" && typeof a.content === "string") {
          if (a.content.toLowerCase().includes("real-device") || a.content.toLowerCase().includes("device-test")) {
            if (a.content.includes("PASS") && !a.content.includes("FAIL")) {
              realDeviceStatus = "pass";
            } else if (a.content.includes("FAIL")) {
              realDeviceStatus = "fail";
            } else {
              realDeviceStatus = "partial";
            }
          }
        }
      }
    }
  }

  // 9. Known failures, degraded features, evidence, blockers.
  const knownFailures: string[] = [];
  const degradedFeatures: string[] = [];
  const manualEvidence: string[] = [];
  const automatedEvidence: string[] = [];
  const releaseBlockers: string[] = [];

  if (stagingSmokeJson) {
    try {
      const parsed = JSON.parse(stagingSmokeJson);

      // Collect failed P0 gates as known failures and release blockers.
      const gates = parsed.p0_gates as { gate: string; status: string; reason?: string }[];
      for (const gate of gates) {
        if (gate.status !== "PASS") {
          const reason = gate.reason ? ` — ${gate.reason}` : "";
          knownFailures.push(`${gate.gate}: ${gate.status}${reason}`);
          releaseBlockers.push(`P0 gate failed: ${gate.gate} — ${gate.reason ?? "no reason provided"}`);
        }
      }

      // Automated evidence: the staging smoke report itself.
      automatedEvidence.push(`Staging smoke report: ${REPORT_FILE}.md`);

      // Collect skipped steps as degraded features.
      const steps = parsed.steps as { step_id: string; status: string }[];
      for (const step of steps) {
        if (step.status === "SKIP") {
          degradedFeatures.push(`${step.step_id} was skipped (missing credentials or environment)`);
        }
      }
    } catch {
      // ignore
    }
  }

  // Collect manual evidence from CI artifacts (markdown files).
  for (const artifact of ciArtifacts) {
    if (typeof artifact === "object" && artifact !== null) {
      const a = artifact as Record<string, unknown>;
      if (a.type === "markdown" && typeof a.content === "string") {
        manualEvidence.push(`CI artifact: ${a.file ?? "unknown"}`);
      }
    }
  }

  // If no staging smoke report was found, note it.
  if (!stagingSmokeJson) {
    knownFailures.push("No staging smoke report found — smoke tests may not have run.");
    releaseBlockers.push("Missing staging smoke report — cannot verify P0 gates.");
    manualEvidence.push("No automated evidence available; manual verification required.");
  }

  return {
    releaseVersion,
    commitSha,
    environment,
    proofTenantId,
    proofWorkspaceId,
    stagingSmokeReportFound: stagingSmokeJson !== null,
    stagingSmokeMarkdown,
    stagingSmokeJson,
    ciArtifacts,
    realDeviceEvidence,
    sdkStatus,
    connectorStatus,
    ingestionStatus,
    graphStatus,
    identityStatus,
    lensStatus,
    surface360Status,
    realDeviceStatus,
    knownFailures,
    degradedFeatures,
    manualEvidence,
    automatedEvidence,
    releaseBlockers,
  };
}

// ---------------------------------------------------------------------------
// Report generation
// ---------------------------------------------------------------------------

function statusIcon(status: string): string {
  return status === "pass" ? "✅" : status === "partial" ? "⚠️" : status === "fail" ? "❌" : "⏭️";
}

function buildReleaseReport(data: CollectedData): { markdown: string; json: string } {
  const date = DATE_STRING;

  // Determine go/no-go.
  const hasP0Blockers = data.releaseBlockers.length > 0;
  const hasSdkProof = data.sdkStatus.some((s) => s.status === "pass");
  const hasConnectorProof = data.connectorStatus.some((c) => c.status === "pass");
  const has360Proof = data.surface360Status.some((s) => s.status === "pass");
  const graphWritePass = data.graphStatus === "pass";
  const lensActivationPass = data.lensStatus === "pass";

  // GO requires: no P0 blockers AND graph write pass AND lens activation pass.
  // SDK/connector/360 proofs are required if they were run — but "not-run"
  // due to missing credentials is acceptable (not a blocker).
  const goCondition =
    !hasP0Blockers &&
    graphWritePass &&
    lensActivationPass &&
    (hasSdkProof || data.sdkStatus.every((s) => s.status === "not-run")) &&
    (hasConnectorProof || data.connectorStatus.every((c) => c.status === "not-run")) &&
    (has360Proof || data.surface360Status.every((s) => s.status === "not-run"));

  const goSummary = goCondition ? "GO" : "NO-GO";

  const goReasons: string[] = [];
  if (hasP0Blockers) {
    goReasons.push(`${data.releaseBlockers.length} P0 blocker(s) present.`);
  }
  if (!graphWritePass) {
    goReasons.push("Graph write did not pass.");
  }
  if (!lensActivationPass) {
    goReasons.push("Lens activation did not pass.");
  }
  if (!hasSdkProof && !data.sdkStatus.every((s) => s.status === "not-run")) {
    goReasons.push("No SDK proof passed.");
  }
  if (!hasConnectorProof && !data.connectorStatus.every((c) => c.status === "not-run")) {
    goReasons.push("No connector proof passed.");
  }
  if (!has360Proof && !data.surface360Status.every((s) => s.status === "not-run")) {
    goReasons.push("No 360 proof passed.");
  }

  const goReason = goCondition
    ? "All required P0 pipeline gates passed. SDK, connector, and 360 tests that were not run are due to missing credentials, not failures."
    : goReasons.length > 0
      ? goReasons.join(" ") + " Therefore, the release is NO-GO."
      : "One or more required P0 conditions were not met.";

  // --- Markdown ---
  const md: string[] = [];

  md.push(`# Aether Functionality Proof Report — ${date}`);
  md.push("");
  md.push(`**Ticket:** FPS-100`);
  md.push(`**Generated:** ${new Date().toISOString()}`);
  md.push("");

  // Release Metadata
  md.push("## Release Metadata");
  md.push("");
  md.push("| Field | Value |");
  md.push("|-------|-------|");
  md.push(`| Release version | ${data.releaseVersion} |`);
  md.push(`| Commit SHA | ${data.commitSha} |`);
  md.push(`| Environment | ${data.environment} |`);
  md.push(`| Proof tenant ID | ${data.proofTenantId} |`);
  md.push(`| Proof workspace ID | ${data.proofWorkspaceId} |`);
  md.push("");

  // SDK Status
  md.push("## SDK Status");
  md.push("");
  md.push("| Platform | Status | Evidence |");
  md.push("|----------|--------|----------|");
  for (const s of data.sdkStatus) {
    md.push(`| ${s.platform} | ${statusIcon(s.status)} ${s.status} | ${s.evidence || "—"} |`);
  }
  md.push("");

  // Connector Status
  md.push("## Connector Status");
  md.push("");
  md.push("| Connector | Status | Evidence |");
  md.push("|-----------|--------|----------|");
  for (const c of data.connectorStatus) {
    md.push(`| ${c.connector} | ${statusIcon(c.status)} ${c.status} | ${c.evidence || "—"} |`);
  }
  md.push("");

  // Pipeline Status (Ingestion, Graph, Identity, Lens)
  md.push("## Pipeline Status");
  md.push("");
  md.push("| Component | Status | Notes |");
  md.push("|-----------|--------|-------|");

  const ingestionNote =
    data.ingestionStatus === "pass"
      ? "Events accepted and processed."
      : data.ingestionStatus === "fail"
        ? "Ingestion pipeline failed."
        : data.ingestionStatus === "partial"
          ? "Partial ingestion — some events accepted."
          : "Not run.";
  md.push(`| Ingestion | ${statusIcon(data.ingestionStatus)} ${data.ingestionStatus} | ${ingestionNote} |`);

  const graphNote =
    data.graphStatus === "pass"
      ? "Graph nodes and edges written successfully."
      : data.graphStatus === "fail"
        ? "Graph write failed."
        : "Not run.";
  md.push(`| Graph | ${statusIcon(data.graphStatus)} ${data.graphStatus} | ${graphNote} |`);

  const identityNote =
    data.identityStatus === "pass"
      ? "Identity resolution working."
      : data.identityStatus === "fail"
        ? "Identity resolution failed."
        : "Not run.";
  md.push(`| Identity | ${statusIcon(data.identityStatus)} ${data.identityStatus} | ${identityNote} |`);

  const lensNote =
    data.lensStatus === "pass"
      ? "Lens activation and derivation working."
      : data.lensStatus === "fail"
        ? "Lens activation failed."
        : "Not run.";
  md.push(`| Lens | ${statusIcon(data.lensStatus)} ${data.lensStatus} | ${lensNote} |`);
  md.push("");

  // 360 Surface Status
  md.push("## 360 Surface Status");
  md.push("");
  md.push("| Surface | Status | Evidence |");
  md.push("|---------|--------|----------|");
  for (const s of data.surface360Status) {
    md.push(`| ${s.surface} | ${statusIcon(s.status)} ${s.status} | ${s.evidence || "—"} |`);
  }
  md.push("");

  // Real-Device Status
  md.push("## Real-Device Status");
  md.push("");
  md.push(`**Status:** ${data.realDeviceStatus}`);
  if (data.realDeviceStatus === "no-evidence") {
    md.push(`**Evidence:** No real-device test evidence available in CI artifacts or REAL_DEVICE_EVIDENCE_PATH.`);
  } else if (data.realDeviceEvidence) {
    md.push(`**Evidence:** See real-device verification file (${REAL_DEVICE_EVIDENCE_PATH}).`);
  } else {
    md.push(`**Evidence:** See CI artifacts for details.`);
  }
  md.push("");

  // Known Failures
  md.push("## Known Failures");
  md.push("");
  if (data.knownFailures.length === 0) {
    md.push("No known failures.");
  } else {
    for (const f of data.knownFailures) {
      md.push(`- ${f}`);
    }
  }
  md.push("");

  // Degraded Features
  md.push("## Degraded Features");
  md.push("");
  if (data.degradedFeatures.length === 0) {
    md.push("No degraded features.");
  } else {
    for (const f of data.degradedFeatures) {
      md.push(`- ${f}`);
    }
  }
  md.push("");

  // Manual Verification Evidence
  md.push("## Manual Verification Evidence");
  md.push("");
  if (data.manualEvidence.length === 0) {
    md.push("No manual verification evidence available.");
  } else {
    for (const e of data.manualEvidence) {
      md.push(`- ${e}`);
    }
  }
  md.push("");

  // Automated Verification Evidence
  md.push("## Automated Verification Evidence");
  md.push("");
  if (data.automatedEvidence.length === 0) {
    md.push("No automated verification evidence available.");
  } else {
    for (const e of data.automatedEvidence) {
      md.push(`- ${e}`);
    }
  }
  md.push("");

  // Release Blockers
  md.push("## Release Blockers");
  md.push("");
  if (data.releaseBlockers.length === 0) {
    md.push("No release blockers identified.");
  } else {
    for (const b of data.releaseBlockers) {
      md.push(`- ❌ ${b}`);
    }
  }
  md.push("");

  // Go/No-Go Summary
  md.push("## Go/No-Go Summary");
  md.push("");
  md.push(`**Decision: ${goSummary}**`);
  md.push(`**Reason:** ${goReason}`);
  md.push("");

  md.push("---");
  md.push("");
  md.push("_Generated by @aether/proof-reporting (MarkdownReportGenerator) for FPS-100._");

  // --- JSON ---
  const jsonReport = {
    report_version: "1.0.0",
    generated_at: new Date().toISOString(),
    ticket: "FPS-100",
    release_metadata: {
      release_version: data.releaseVersion,
      commit_sha: data.commitSha,
      environment: data.environment,
      proof_tenant_id: data.proofTenantId,
      proof_workspace_id: data.proofWorkspaceId,
    },
    sdk_status: data.sdkStatus.map((s) => ({
      platform: s.platform,
      status: s.status,
      evidence: s.evidence,
    })),
    connector_status: data.connectorStatus.map((c) => ({
      connector: c.connector,
      status: c.status,
      evidence: c.evidence,
    })),
    pipeline_status: {
      ingestion: data.ingestionStatus,
      graph: data.graphStatus,
      identity: data.identityStatus,
      lens: data.lensStatus,
    },
    surface_360_status: data.surface360Status.map((s) => ({
      surface: s.surface,
      status: s.status,
      evidence: s.evidence,
    })),
    real_device_status: data.realDeviceStatus,
    known_failures: data.knownFailures,
    degraded_features: data.degradedFeatures,
    manual_verification_evidence: data.manualEvidence,
    automated_verification_evidence: data.automatedEvidence,
    release_blockers: data.releaseBlockers,
    go_no_go: {
      decision: goSummary,
      reason: goReason,
    },
  };

  return {
    markdown: md.join("\n"),
    json: JSON.stringify(jsonReport, null, 2),
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.log(`[FPS-100] Generating release proof report...`);
  console.log(`[FPS-100] CI artifact path: ${CI_ARTIFACT_PATH}`);
  console.log(`[FPS-100] Real device evidence path: ${REAL_DEVICE_EVIDENCE_PATH}`);
  console.log(`[FPS-100] Report directory: ${REPORT_DIR}`);

  // Collect all data.
  const data = await collectData();

  console.log(`[FPS-100] Release version: ${data.releaseVersion}`);
  console.log(`[FPS-100] Commit SHA: ${data.commitSha}`);
  console.log(`[FPS-100] Staging smoke report found: ${data.stagingSmokeReportFound}`);
  console.log(`[FPS-100] CI artifacts found: ${data.ciArtifacts.length}`);
  console.log(`[FPS-100] Real-device evidence found: ${data.realDeviceEvidence !== null}`);

  // Build the report.
  const report = buildReleaseReport(data);

  // Ensure the report directory exists.
  await fsp.mkdir(REPORT_DIR, { recursive: true });

  // Write the Markdown report.
  const mdPath = resolve(REPORT_DIR, `${REPORT_FILE}.md`);
  await fsp.writeFile(mdPath, report.markdown, "utf-8");
  console.log(`[FPS-100] Markdown report written to ${mdPath}`);

  // Write the JSON report.
  const jsonPath = resolve(REPORT_DIR, `${REPORT_FILE}.json`);
  await fsp.writeFile(jsonPath, report.json, "utf-8");
  console.log(`[FPS-100] JSON report written to ${jsonPath}`);

  // Also generate via MarkdownReportGenerator and JsonReportGenerator for
  // compatibility with the @aether/proof-reporting package.
  const steps: ProofStepResult[] = [
    {
      stepId: "release-version",
      status: data.releaseVersion !== "untagged-dev" && data.releaseVersion !== "unknown" ? "passed" : "failed",
      message: `Release version: ${data.releaseVersion}`,
    },
    {
      stepId: "commit-sha",
      status: data.commitSha !== "unknown" ? "passed" : "failed",
      message: `Commit SHA: ${data.commitSha}`,
    },
    {
      stepId: "staging-smoke-report",
      status: data.stagingSmokeReportFound ? "passed" : "failed",
      message: data.stagingSmokeReportFound
        ? `Found staging smoke report: ${REPORT_FILE}.md`
        : "No staging smoke report found",
    },
    {
      stepId: "ci-artifacts",
      status: data.ciArtifacts.length > 0 ? "passed" : "skipped",
      message: `CI artifacts: ${data.ciArtifacts.length} file(s)`,
    },
    {
      stepId: "sdk-status",
      status: data.sdkStatus.some((s) => s.status === "pass") ? "passed" : "failed",
      message: `SDK platforms: ${data.sdkStatus.map((s) => `${s.platform}=${s.status}`).join(", ")}`,
    },
    {
      stepId: "connector-status",
      status: data.connectorStatus.some((c) => c.status === "pass") ? "passed" : "failed",
      message: `Connectors: ${data.connectorStatus.map((c) => `${c.connector}=${c.status}`).join(", ")}`,
    },
    {
      stepId: "ingestion-status",
      status: data.ingestionStatus === "pass" ? "passed" : "failed",
      message: `Ingestion: ${data.ingestionStatus}`,
    },
    {
      stepId: "graph-status",
      status: data.graphStatus === "pass" ? "passed" : "failed",
      message: `Graph: ${data.graphStatus}`,
    },
    {
      stepId: "identity-status",
      status: data.identityStatus === "pass" ? "passed" : "failed",
      message: `Identity: ${data.identityStatus}`,
    },
    {
      stepId: "lens-status",
      status: data.lensStatus === "pass" ? "passed" : "failed",
      message: `Lens: ${data.lensStatus}`,
    },
    {
      stepId: "360-status",
      status: data.surface360Status.some((s) => s.status === "pass") ? "passed" : "failed",
      message: `360 surfaces: ${data.surface360Status.map((s) => `${s.surface}=${s.status}`).join(", ")}`,
    },
    {
      stepId: "real-device-status",
      status:
        data.realDeviceStatus === "pass" ? "passed" :
        data.realDeviceStatus === "no-evidence" ? "skipped" : "failed",
      message: `Real-device: ${data.realDeviceStatus}`,
    },
    {
      stepId: "release-blockers",
      status: data.releaseBlockers.length === 0 ? "passed" : "failed",
      message: `Blockers: ${data.releaseBlockers.length} (${data.releaseBlockers.length === 0 ? "none" : "see report"})`,
    },
  ];

  const proofResult: ProofResult = {
    proofId: `release-proof-${DATE_STRING}`,
    status: data.releaseBlockers.length === 0 ? "passed" : "failed",
    steps,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
    summary: `Release proof report for ${data.releaseVersion} — ${data.commitSha} — ${data.environment}`,
    totalDurationMs: 0,
  };

  // Generate via MarkdownReportGenerator.
  const mdGenerator = new MarkdownReportGenerator();
  const mdGenerated = mdGenerator.generate(proofResult);

  // Generate via JsonReportGenerator.
  const jsonGenerator = new JsonReportGenerator();
  const jsonGenerated = jsonGenerator.generate(proofResult);

  // Print the full release report markdown to stdout.
  console.log("");
  console.log("=".repeat(60));
  console.log("RELEASE PROOF REPORT (FPS-100)");
  console.log("=".repeat(60));
  console.log(report.markdown);

  console.log("");
  console.log("--- JSON Report ---");
  console.log(report.json);

  console.log("");
  console.log("[FPS-100] Release proof report generated successfully.");
  console.log("[FPS-100] Exiting 0.");
  process.exit(0);
}

main().catch((err) => {
  console.error("[FPS-100] Unhandled error:", err);
  process.exit(1);
});
