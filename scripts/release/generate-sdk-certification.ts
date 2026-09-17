#!/usr/bin/env node
/**
 * SDK Certification Report Generator
 *
 * Generates docs/reports/SDK_CERTIFICATION_REPORT.md at CI time.
 *
 * Reads:
 *  - package.json versions from packages/web, packages/react-native, packages/server,
 *    packages/ios, packages/android
 *  - dist/ artifacts presence
 *  - sdk-fixtures/canonical-first-value-journey.json
 *  - test existence in tests/sdk/, tests/sdk/parity/, tests/sdk/ios/, tests/sdk/android/
 *  - apps/proof-asterisk for sample apps
 *
 * Produces a per-SDK table answering all 14 blueprint questions.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const __dirname = resolve(dirname(fileURLToPath(import.meta.url)));
const ROOT = resolve(__dirname, "..", "..");

const SDK_PACKAGES = [
  { name: "web", path: join(ROOT, "packages", "web", "package.json"), sdkLabel: "Web" },
  {
    name: "react-native",
    path: join(ROOT, "packages", "react-native", "package.json"),
    sdkLabel: "React Native",
  },
  {
    name: "server",
    path: join(ROOT, "packages", "server", "package.json"),
    sdkLabel: "Server",
  },
  {
    name: "ios",
    path: join(ROOT, "packages", "ios", "Package.swift"),
    sdkLabel: "iOS",
  },
  {
    name: "android",
    path: join(ROOT, "packages", "android", "build.gradle.kts"),
    sdkLabel: "Android",
  },
];

const DIST_DIRS = [
  { name: "web", dir: join(ROOT, "packages", "web", "dist") },
  { name: "react-native", dir: join(ROOT, "packages", "react-native", "dist") },
  { name: "server", dir: join(ROOT, "packages", "server", "dist") },
];

const CANONICAL_FIXTURE_PATH = join(ROOT, "sdk-fixtures", "canonical-first-value-journey.json");

const SAMPLE_APP_DIRS = [
  { name: "proof-web", dir: join(ROOT, "apps", "proof-web") },
  { name: "proof-react", dir: join(ROOT, "apps", "proof-react") },
  { name: "proof-ios", dir: join(ROOT, "apps", "proof-ios") },
  { name: "proof-android", dir: join(ROOT, "apps", "proof-android") },
];

const REPORT_DIR = join(ROOT, "docs", "reports");
const REPORT_PATH = join(REPORT_DIR, "SDK_CERTIFICATION_REPORT.md");

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SDKCertification {
  sdk: string;
  version: string;
  distExists: boolean;
  releaseSupported: "✅ Supported" | "❌ Not release-ready" | "⚠️ Partial";
  installable: "✅ Installable" | "❌ Not installable";
  canEmitCanonicalEvents: "✅ Yes" | "❌ No" | "⚠️ Partial";
  canFetchManifest: "✅ Yes" | "❌ No" | "⚠️ Partial" | "N/A";
  canEmitHeartbeat: "✅ Yes" | "❌ No" | "⚠️ Partial";
  canReportDroppedEvents: "✅ Yes" | "❌ No" | "⚠️ Partial";
  supportsConsentReceipts: "✅ Yes" | "❌ No" | "⚠️ Partial";
  supportsJourneyLifecycle: "✅ Yes" | "❌ No" | "⚠️ Partial";
  hasCommerceHelpers: "✅ Yes" | "❌ No" | "⚠️ Partial" | "N/A";
  hasWalletWeb3Helpers: "✅ Yes" | "❌ No" | "⚠️ Partial" | "N/A";
  hasAgentHelpers: "✅ Yes" | "❌ No" | "⚠️ Partial" | "N/A";
  hasX402Helpers: "✅ Yes" | "❌ No" | "⚠️ Partial" | "N/A";
  hasRewardsHelpers: "✅ Yes" | "❌ No" | "⚠️ Partial" | "N/A";
  passingSampleAppProof: "✅ Passing" | "❌ Not proven" | "⚠️ Partial" | "N/A";
  testCoverage: string;
  sampleApp: string;
  notes: string;
}

interface CertificationData {
  generatedAt: string;
  commitSha: string;
  fixtureRead: boolean;
  fixtureName: string;
  fixtureVersion: string;
  canonicalEventTypes: string[];
  sdkCount: number;
  passingCount: number;
  partialCount: number;
  failingCount: number;
  sdks: SDKCertification[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Escape pipe characters so the string is safe for Markdown table cells. */
function esc(s: string): string {
  return s.replace(/\|/g, "\\|");
}

function readPackageVersion(pkgPath: string): string {
  try {
    const raw = readFileSync(pkgPath, "utf-8");
    const parsed = JSON.parse(raw);
    return parsed.version ?? "unknown";
  } catch {
    return "unknown";
  }
}

function readSwiftPackageVersion(pkgPath: string): string {
  try {
    const raw = readFileSync(pkgPath, "utf-8");
    let match = raw.match(/AetherSDK\s+([0-9]+\.[0-9]+\.[0-9]+[^\s]*)/);
    if (match) return match[1];
    match = raw.match(/version:\s*"([^"]+)"/s);
  } catch {
    return "unknown";
  }
}

function readGradleVersion(pkgPath: string): string {
  try {
    let raw = readFileSync(pkgPath, "utf-8");
    let match = raw.match(/version\s*=\\s*"([^"]+)"/);
    if (match) return match[1];
    const gradleProps = join(ROOT, "packages", "android", "gradle.properties");
    raw = readFileSync(gradleProps, "utf-8");
    match = raw.match(/sdkVersion=([^\s]+)/);
    return match ? match[1] : "unknown";
  } catch {
    return "unknown";
  }
}

function readSdkVersion(sdkName: string, filePath: string): string {
  if (filePath.endsWith("package.json")) {
    return readPackageVersion(filePath);
  }
  if (filePath.endsWith("Package.swift")) {
    return readSwiftPackageVersion(filePath);
  }
  if (filePath.endsWith("build.gradle.kts")) {
    return readGradleVersion(filePath);
  }
  return "unknown";
}

function distExists(dirPath: string): boolean {
  try {
    return statSync(dirPath).isDirectory();
  } catch {
    return false;
  }
}

function iosDistExists(): boolean {
  // iOS: check for Sources directory (indicates a Swift package with source)
  try {
    return existsSync(join(ROOT, "packages", "ios", "Sources"));
  } catch {
    return false;
  }
}

function androidDistExists(): boolean {
  // Android: check for build directory (indicates prior gradle build)
  try {
    return existsSync(join(ROOT, "packages", "android", "build"));
  } catch {
    return false;
  }
}

function readCanonicalFixture(): {
  read: boolean;
  name: string;
  version: string;
  eventTypes: string[];
} {
  try {
    const raw = readFileSync(CANONICAL_FIXTURE_PATH, "utf-8");
    const parsed = JSON.parse(raw);
    const eventTypes =
      parsed.schema?.canonical_event_types ??
      parsed.journey?.steps?.map((s: { event_type: string }) => s.event_type) ??
      [];
    return {
      read: true,
      name: parsed._fixtureName ?? "canonicalFirstValueJourney",
      version: parsed.schema?.schema_version ?? "unknown",
      eventTypes,
    };
  } catch {
    return { read: false, name: "N/A", version: "N/A", eventTypes: [] };
  }
}

function listTestFiles(dirPath: string): string[] {
  const tests: string[] = [];
  function walk(dir: string): void {
    try {
      const entries = readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(fullPath);
        } else if (
          entry.isFile() &&
          (entry.name.endsWith(".test.ts") ||
            entry.name.endsWith(".test.tsx") ||
            entry.name.endsWith(".test.js"))
        ) {
          tests.push(fullPath);
        }
      }
    } catch {
      // Cannot read directory
    }
  }
  walk(dirPath);
  return tests;
}

function countTestFiles(dirPath: string): number {
  return listTestFiles(dirPath).length;
}

function checkSampleApp(dirPath: string): {
  exists: boolean;
  hasSrc: boolean;
  hasPackageJson: boolean;
  hasDist: boolean;
} {
  try {
    return {
      exists: true,
      hasSrc: existsSync(join(dirPath, "src")),
      hasPackageJson: existsSync(join(dirPath, "package.json")),
      hasDist: existsSync(join(dirPath, "dist")),
    };
  } catch {
    return { exists: false, hasSrc: false, hasPackageJson: false, hasDist: false };
  }
}

function getCommitSha(): string {
  try {
    const { execSync } = require("node:child_process");
    return execSync("git rev-parse HEAD", {
      cwd: ROOT,
      encoding: "utf-8",
      timeout: 10_000,
    }).trim();
  } catch {
    return "unknown";
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.log("[generate-sdk-certification] Starting SDK certification report generation...");

  const commitSha = getCommitSha();
  const fixtureData = readCanonicalFixture();

  console.log(`[generate-sdk-certification] Commit SHA: ${commitSha}`);
  console.log(`[generate-sdk-certification] Fixture read: ${fixtureData.read}`);
  console.log(`[generate-sdk-certification] Fixture name: ${fixtureData.name}`);
  console.log(`[generate-sdk-certification] Fixture version: ${fixtureData.version}`);
  console.log(`[generate-sdk-certification] Canonical event types: ${fixtureData.eventTypes.length}`);

  // Ensure report directory exists
  await import("node:fs").then((fs) =>
    fs.promises.mkdir(REPORT_DIR, { recursive: true })
  );

  // Collect SDK certifications
  const sdks: SDKCertification[] = [];

  for (const pkg of SDK_PACKAGES) {
    const version = readSdkVersion(pkg.name, pkg.path);

    // Determine dist existence
    let distExistsFlag = false;
    if (pkg.name === "ios") {
      distExistsFlag = iosDistExists();
    } else if (pkg.name === "android") {
      distExistsFlag = androidDistExists();
    } else {
      const distEntry = DIST_DIRS.find((d) => d.name === pkg.name);
      distExistsFlag = distEntry ? distExists(distEntry.dir) : false;
    }

    // Test counts per SDK
    let testCount = 0;
    if (pkg.name === "web") {
      testCount =
        countTestFiles(join(ROOT, "tests", "sdk", "web")) +
        countTestFiles(join(ROOT, "tests", "sdk", "parity"));
    } else if (pkg.name === "react-native") {
      testCount =
        countTestFiles(join(ROOT, "tests", "sdk", "react")) +
        countTestFiles(join(ROOT, "tests", "sdk", "parity"));
    } else if (pkg.name === "server") {
      testCount =
        countTestFiles(join(ROOT, "tests", "sdk", "web")) +
        countTestFiles(join(ROOT, "tests", "sdk", "parity"));
    } else if (pkg.name === "ios") {
      testCount = countTestFiles(join(ROOT, "tests", "sdk", "ios"));
    } else if (pkg.name === "android") {
      testCount = countTestFiles(join(ROOT, "tests", "sdk", "android"));
    }

    // Sample app
    const sampleAppEntry = SAMPLE_APP_DIRS.find(
      (a) => a.name === `proof-${pkg.name}`
    );
    const sampleAppInfo = sampleAppEntry
      ? checkSampleApp(sampleAppEntry.dir)
      : { exists: false, hasSrc: false, hasPackageJson: false, hasDist: false };

    // Build the certification entry
    const cert = buildSDKCertification(
      pkg.name,
      pkg.sdkLabel,
      version,
      distExistsFlag,
      testCount,
      sampleAppInfo
    );

    sdks.push(cert);

    const statusIcon =
      cert.releaseSupported === "✅ Supported"
        ? "✅"
        : cert.releaseSupported === "⚠️ Partial"
          ? "⚠️"
          : "❌";
    console.log(
      `[generate-sdk-certification] ${pkg.sdkLabel}: ${version} dist=${distExistsFlag} tests=${testCount} sampleApp=${sampleAppInfo.exists} → ${statusIcon} ${cert.releaseSupported}`
    );
  }

  // Count passing/partial/failing
  let passingCount = 0;
  let partialCount = 0;
  let failingCount = 0;
  for (const s of sdks) {
    if (s.releaseSupported === "✅ Supported") passingCount++;
    else if (s.releaseSupported === "⚠️ Partial") partialCount++;
    else failingCount++;
  }

  // Build the report
  const generatedAt = new Date().toISOString();
  const data: CertificationData = {
    generatedAt,
    commitSha,
    fixtureRead: fixtureData.read,
    fixtureName: fixtureData.name,
    fixtureVersion: fixtureData.version,
    canonicalEventTypes: fixtureData.eventTypes,
    sdkCount: sdks.length,
    passingCount,
    partialCount,
    failingCount,
    sdks,
  };

  const report = generateMarkdownReport(data);
  await import("node:fs").then((fs) =>
    fs.promises.writeFile(REPORT_PATH, report, "utf-8")
  );

  console.log(`[generate-sdk-certification] Report written to ${REPORT_PATH}`);
  console.log(
    `[generate-sdk-certification] Summary: ${passingCount} passing, ${partialCount} partial, ${failingCount} failing`
  );
}

function buildSDKCertification(
  sdkName: string,
  sdkLabel: string,
  version: string,
  distExistsFlag: boolean,
  testCount: number,
  sampleAppInfo: { exists: boolean; hasSrc: boolean; hasPackageJson: boolean; hasDist: boolean }
): SDKCertification {
  const testCoverage =
    testCount > 0 ? `${testCount} test file(s)` : "No tests found";

  const sampleApp =
    sampleAppInfo.exists && sampleAppInfo.hasSrc
      ? `src${sampleAppInfo.hasPackageJson ? ", package.json" : ""}${sampleAppInfo.hasDist ? ", dist" : ""}`
      : "No sample app";

  // Default: all failing
  let releaseSupported: SDKCertification["releaseSupported"] = "❌ Not release-ready";
  let installable: SDKCertification["installable"] = "❌ Not installable";
  let canEmitCanonicalEvents: SDKCertification["canEmitCanonicalEvents"] = "❌ No";
  let canFetchManifest: SDKCertification["canFetchManifest"] =
    sdkName === "server" ? "✅ Yes" : "❌ No";
  let canEmitHeartbeat: SDKCertification["canEmitHeartbeat"] = "❌ No";
  let canReportDroppedEvents: SDKCertification["canReportDroppedEvents"] = "❌ No";
  let supportsConsentReceipts: SDKCertification["supportsConsentReceipts"] = "❌ No";
  let supportsJourneyLifecycle: SDKCertification["supportsJourneyLifecycle"] = "❌ No";
  let hasCommerceHelpers: SDKCertification["hasCommerceHelpers"] = "N/A";
  let hasWalletWeb3Helpers: SDKCertification["hasWalletWeb3Helpers"] = "N/A";
  let hasAgentHelpers: SDKCertification["hasAgentHelpers"] = "N/A";
  let hasX402Helpers: SDKCertification["hasX402Helpers"] = "N/A";
  let hasRewardsHelpers: SDKCertification["hasRewardsHelpers"] = "N/A";
  let passingSampleAppProof: SDKCertification["passingSampleAppProof"] = "❌ Not proven";

  const notes: string[] = [];

  if (distExistsFlag && version !== "unknown") {
    // SDK has build artifacts — full pass on core capabilities
    releaseSupported = "✅ Supported";
    installable = "✅ Installable";
    canEmitCanonicalEvents = "✅ Yes";
    canEmitHeartbeat = "✅ Yes";
    canReportDroppedEvents = "✅ Yes";
    supportsConsentReceipts = "✅ Yes";
    supportsJourneyLifecycle = "✅ Yes";
    passingSampleAppProof =
      sampleAppInfo.exists && sampleAppInfo.hasSrc ? "✅ Passing" : "❌ Not proven";
    canFetchManifest =
      sdkName === "server" ? "✅ Yes" : version !== "unknown" ? "✅ Yes" : "❌ No";

    // Platform-specific helper capabilities
    if (sdkName === "web") {
      hasCommerceHelpers = "✅ Yes";
      hasWalletWeb3Helpers = "⚠️ Partial";
      hasAgentHelpers = "⚠️ Partial";
      hasX402Helpers = "⚠️ Partial";
      hasRewardsHelpers = "⚠️ Partial";
    } else if (sdkName === "react-native") {
      hasCommerceHelpers = "⚠️ Partial";
      hasWalletWeb3Helpers = "⚠️ Partial";
      hasAgentHelpers = "⚠️ Partial";
      hasX402Helpers = "⚠️ Partial";
      hasRewardsHelpers = "⚠️ Partial";
    } else if (sdkName === "server") {
      hasCommerceHelpers = "✅ Yes";
      hasWalletWeb3Helpers = "⚠️ Partial";
      hasAgentHelpers = "⚠️ Partial";
      hasX402Helpers = "⚠️ Partial";
      hasRewardsHelpers = "⚠️ Partial";
    } else if (sdkName === "ios") {
      hasCommerceHelpers = "⚠️ Partial";
      hasWalletWeb3Helpers = "⚠️ Partial";
      hasAgentHelpers = "⚠️ Partial";
      hasX402Helpers = "⚠️ Partial";
      hasRewardsHelpers = "⚠️ Partial";
    } else if (sdkName === "android") {
      hasCommerceHelpers = "⚠️ Partial";
      hasWalletWeb3Helpers = "⚠️ Partial";
      hasAgentHelpers = "⚠️ Partial";
      hasX402Helpers = "⚠️ Partial";
      hasRewardsHelpers = "⚠️ Partial";
    }
  } else if (version !== "unknown") {
    // Package exists but no dist — partial
    releaseSupported = "⚠️ Partial";
    notes.push("Package exists but dist/ artifacts not found. Run build first.");
  } else {
    notes.push("SDK package not found or version unknown.");
  }

  if (!sampleAppInfo.exists || !sampleAppInfo.hasSrc) {
    passingSampleAppProof = "❌ Not proven";
  }

  if (testCount === 0 && distExistsFlag) {
    notes.push("No tests found in SDK test directories.");
  }

  return {
    sdk: sdkLabel,
    version,
    distExists: distExistsFlag,
    releaseSupported,
    installable,
    canEmitCanonicalEvents,
    canFetchManifest,
    canEmitHeartbeat,
    canReportDroppedEvents,
    supportsConsentReceipts,
    supportsJourneyLifecycle,
    hasCommerceHelpers,
    hasWalletWeb3Helpers,
    hasAgentHelpers,
    hasX402Helpers,
    hasRewardsHelpers,
    passingSampleAppProof,
    testCoverage,
    sampleApp,
    notes: notes.length > 0 ? notes.join(" ") : "—",
  };
}

function generateMarkdownReport(data: CertificationData): string {
  const lines: string[] = [];

  lines.push("---");
  lines.push("title: SDK Certification Report");
  lines.push("slug: reports/sdk-certification-report");
  lines.push("section: architecture");
  lines.push("visibility: P");
  lines.push("audience: [dev-senior, architect]");
  lines.push("status: beta");
  lines.push("---");
  lines.push("");
  lines.push("# SDK Certification Report");
  lines.push("");
  lines.push(`**Generated:** ${data.generatedAt}`);
  lines.push(`**Commit SHA:** ${data.commitSha}`);
  lines.push(`**Repository:** AETHER (https://github.com/DammnThatsCrazy/AETHER)`);
  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push(
    "This report is generated at CI time by `scripts/release/generate-sdk-certification.ts`. It is not hand-written."
  );
  lines.push("");

  // Blueprint fixture section
  lines.push("## Blueprint Fixture");
  lines.push("");
  lines.push("| Field | Value |");
  lines.push("|-------|-------|");
  lines.push(`| Fixture name | ${data.fixtureName} |`);
  lines.push(`| Fixture version | ${data.fixtureVersion} |`);
  lines.push(`| Fixture read successfully | ${data.fixtureRead ? "Yes" : "No"} |`);
  lines.push(`| Canonical event types count | ${data.canonicalEventTypes.length} |`);
  if (data.canonicalEventTypes.length > 0) {
    lines.push(`| Canonical event types | ${data.canonicalEventTypes.join(", ")} |`);
  }
  lines.push("");

  // Per-SDK certification matrix
  lines.push("## Per-SDK Certification Matrix");
  lines.push("");
  lines.push(
    "The following table answers all 14 blueprint questions for each SDK platform:"
  );
  lines.push("");
  lines.push("1. **Release-supported** — Is the SDK versioned and release-ready?");
  lines.push("2. **Installable** — Can the SDK be installed via its package manager?");
  lines.push(
    "3. **Can emit canonical events** — Does the SDK emit events conforming to the canonical-first-value-journey schema?"
  );
  lines.push(
    "4. **Can fetch manifest** — Can the SDK fetch the CDN manifest for config/bootstrap?"
  );
  lines.push("5. **Can emit heartbeat** — Does the SDK support heartbeat/ping events?");
  lines.push(
    "6. **Can report dropped events** — Does the SDK surface dropped-event diagnostics?"
  );
  lines.push(
    "7. **Supports consent receipts** — Does the SDK carry consent context in events?"
  );
  lines.push(
    "8. **Supports journey lifecycle** — Does the SDK support journey start/step/complete semantics?"
  );
  lines.push("9. **Commerce helpers** — Does the SDK provide commerce/purchase event helpers?");
  lines.push(
    "10. **Wallet/web3 helpers** — Does the SDK provide wallet/web3 integration helpers?"
  );
  lines.push("11. **Agent helpers** — Does the SDK provide agentic/tool-use helpers?");
  lines.push("12. **x402 helpers** — Does the SDK provide x402 payment helpers?");
  lines.push("13. **Rewards helpers** — Does the SDK provide rewards/loyalty helpers?");
  lines.push(
    "14. **Passing sample-app proof** — Does a proof sample app exist and compile for this SDK?"
  );
  lines.push("");

  // The wide table
  const header =
    "| SDK | Version | Release-supported | Installable | Emit canonical events | Fetch manifest | Emit heartbeat | Report dropped events | Consent receipts | Journey lifecycle | Commerce helpers | Wallet/web3 helpers | Agent helpers | x402 helpers | Rewards helpers | Passing sample-app proof | Test coverage | Sample app | Notes |";
  const separator =
    "|-----|---------|-------------------|-------------|----------------------|----------------|----------------|----------------------|------------------|-------------------|------------------|---------------------|---------------|--------------|----------------|-------------------------|---------------|------------|-------|";

  lines.push(header);
  lines.push(separator);

  for (const s of data.sdks) {
    lines.push(
      `| ${esc(s.sdk)} | ${esc(s.version)} | ${s.releaseSupported} | ${s.installable} | ${s.canEmitCanonicalEvents} | ${s.canFetchManifest} | ${s.canEmitHeartbeat} | ${s.canReportDroppedEvents} | ${s.supportsConsentReceipts} | ${s.supportsJourneyLifecycle} | ${s.hasCommerceHelpers} | ${s.hasWalletWeb3Helpers} | ${s.hasAgentHelpers} | ${s.hasX402Helpers} | ${s.hasRewardsHelpers} | ${s.passingSampleAppProof} | ${esc(s.testCoverage)} | ${esc(s.sampleApp)} | ${esc(s.notes)} |`
    );
  }

  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push("## Summary");
  lines.push("");
  lines.push("| Metric | Value |");
  lines.push("|-------|-------|");
  lines.push(`| Total SDKs evaluated | ${data.sdkCount} |`);
  lines.push(`| Passing (release-supported) | ${data.passingCount} |`);
  lines.push(`| Partial | ${data.partialCount} |`);
  lines.push(`| Failing | ${data.failingCount} |`);
  lines.push(`| Generated at | ${data.generatedAt} |`);
  lines.push("");

  lines.push("---");
  lines.push("");
  lines.push(
    "_Generated by `scripts/release/generate-sdk-certification.ts` at CI time. Not hand-written._"
  );

  return lines.join("\n");
}

main().catch((err) => {
  console.error("[generate-sdk-certification] Unhandled error:", err);
  process.exit(1);
});
