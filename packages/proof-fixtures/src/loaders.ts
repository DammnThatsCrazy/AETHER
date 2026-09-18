import { readFile, readdir } from "fs/promises";
import { join } from "path";
import {
  GraphNode,
  GraphEdge,
  ProfileIdentity,
  Campaign,
  Communication,
  LensOutput,
} from "@aether/proof-contracts";

/** Absolute path to the fixtures/ directory. */
export function fixturesDir(): string {
  return join(__dirname, "..", "fixtures");
}

// ─────────────────────────────────────────────
//  Domain routing — maps a single fixtureKey to a fixture subdirectory.
// ─────────────────────────────────────────────

/** Supported domains and their fixture subdirectories. */
const DOMAINS = [
  "sdk-events",
  "stripe",
  "shopify",
  "email",
  "identity",
  "journeys",
  "conversions",
  "value",
  "graph",
  "lenses",
  "360",
] as const;

type Domain = (typeof DOMAINS)[number];

/**
 * SDK event keys map one-to-one to files inside fixtures/sdk-events/.
 * Each key is the bare filename without .json (e.g. 'heartbeat' -> heartbeat.json).
 */
const SDK_EVENT_KEYS = [
  "heartbeat",
  "page-view",
  "screen-view",
  "custom-event",
  "identify",
  "alias",
  "conversion",
  "session-started",
  "session-ended",
  "consent-disabled",
  "offline-queued",
  "offline-flushed",
] as const;

/**
 * Resolve a fixture key to its fixture subdirectory path.
 *
 * Mapping rules:
 *   - "sdk-heartbeat", "sdk-page-view", … -> fixtures/sdk-events/<key>.json
 *     (any key prefixed "sdk-" plus an SDK event key name)
 *   - "stripe-*"                          -> fixtures/stripe/
 *   - "shopify-*"                          -> fixtures/shopify/
 *   - "email-*"                            -> fixtures/email/
 *   - "identity-*"                         -> fixtures/identity/
 *   - "journey-*"                          -> fixtures/journeys/
 *   - "conversion-*"                       -> fixtures/conversions/
 *   - "value-*"                            -> fixtures/value/
 *   - "graph-*"                            -> fixtures/graph/
 *   - "lens-*"                             -> fixtures/lenses/
 *   - "th60-*"                             -> fixtures/360/
 *
 * If the key doesn't match a known domain, throws a descriptive error.
 */
export function findFixtureDir(fixtureKey: string): string {
  const trimmed = fixtureKey.trim();

  // Bare SDK event names (no prefix): "heartbeat" -> fixtures/sdk-events/heartbeat.json
  if (SDK_EVENT_KEYS.includes(trimmed as any)) {
    return join(fixturesDir(), "sdk-events", `${trimmed}.json`);
  }

  // SDK event keys: "sdk-<event-name>" -> fixtures/sdk-events/<event-name>.json
  if (trimmed.startsWith("sdk-")) {
    const eventName = trimmed.slice(4);
    if (SDK_EVENT_KEYS.includes(eventName as any)) {
      return join(fixturesDir(), "sdk-events", `${eventName}.json`);
    }
    throw new Error(
      `Unknown SDK event key "${trimmed}". ` +
        `Supported SDK event keys: ${SDK_EVENT_KEYS.join(", ")}`,
    );
  }

  // Connector / domain-prefixed keys: "<domain>-<rest>" -> fixtures/<domain>/
  for (const domain of DOMAINS) {
    if (trimmed.startsWith(domain + "-") || trimmed === domain) {
      return join(fixturesDir(), domain);
    }
  }

  // Bare domain name fallback
  if (DOMAINS.includes(trimmed as any)) {
    return join(fixturesDir(), trimmed);
  }

  throw new Error(
    `Unknown fixture key "${trimmed}". ` +
      `Supported domains: ${DOMAINS.join(", ")}. ` +
      `SDK event keys: ${SDK_EVENT_KEYS.join(", ")} ` +
      `(use "sdk-<key>" or bare "<key>").`,
  );
}

// ─────────────────────────────────────────────
//  Available-fixtures enumeration
// ─────────────────────────────────────────────

/**
 * List available fixture files inside a domain directory.
 * Returns filenames without the .json extension.
 */
export async function listAvailableFixtures(domainDir: string): Promise<string[]> {
  try {
    const entries = await readdir(domainDir);
    return entries
      .filter((e) => e.endsWith(".json"))
      .map((e) => e.slice(0, -5)); // strip .json
  } catch {
    return [];
  }
}

// ─────────────────────────────────────────────
//  Loader functions (keyed API)
// ─────────────────────────────────────────────

/**
 * Load raw_input.json for a given fixture key.
 *
 *   loadRawFixture("sdk-heartbeat")          -> fixtures/sdk-events/heartbeat.json
 *   loadRawFixture("stripe-customer")        -> fixtures/stripe/raw_input.json
 *   loadRawFixture("shopify-order")          -> fixtures/shopify/raw_input.json
 */
export async function loadRawFixture(
  fixtureKey: string,
): Promise<Record<string, unknown>> {
  const dir = findFixtureDir(fixtureKey);

  // SDK event keys resolve to a single .json file, not a directory
  if (dir.endsWith(".json")) {
    return readJSONFile(dir, `raw fixture for "${fixtureKey}"`);
  }

  const file = join(dir, "raw_input.json");
  return readJSONFile(file, `raw_input.json for "${fixtureKey}"`);
}

/**
 * Load expected_normalized.json for a given fixture key.
 */
export async function loadExpectedNormalized(
  fixtureKey: string,
): Promise<Record<string, unknown>> {
  const dir = findFixtureDir(fixtureKey);

  if (dir.endsWith(".json")) {
    throw new Error(
      `Cannot load expected_normalized for SDK event key "${fixtureKey}" ` +
        `(single-file fixture, no normalized output available)`,
    );
  }

  const file = join(dir, "expected_normalized.json");
  return readJSONFile(file, `expected_normalized.json for "${fixtureKey}"`);
}

/**
 * Load expected graph outputs (nodes + edges) for a fixture key.
 */
export async function loadExpectedGraphOutputs(
  fixtureKey: string,
): Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] }> {
  const dir = findFixtureDir(fixtureKey);

  if (dir.endsWith(".json")) {
    throw new Error(
      `Cannot load graph outputs for SDK event key "${fixtureKey}" ` +
        `(single-file fixture, no graph output available)`,
    );
  }

  const nodesFile = join(dir, "expected_graph_nodes.json");
  const edgesFile = join(dir, "expected_graph_edges.json");

  const [nodesRaw, edgesRaw] = await Promise.all([
    readJSONFile(nodesFile, `expected_graph_nodes.json for "${fixtureKey}"`),
    readJSONFile(edgesFile, `expected_graph_edges.json for "${fixtureKey}"`),
  ]);

  return {
    nodes: (nodesRaw as unknown) as Record<string, unknown>[],
    edges: (edgesRaw as unknown) as Record<string, unknown>[],
  };
}

/**
 * Load 360-view expected outputs (profile + campaign + communications).
 */
export async function loadExpected360Outputs(
  fixtureKey: string,
): Promise<{
  profile: Record<string, unknown>;
  campaign: Record<string, unknown>;
  communications: Record<string, unknown>[];
}> {
  const dir = findFixtureDir(fixtureKey);

  if (dir.endsWith(".json")) {
    throw new Error(
      `Cannot load 360 outputs for SDK event key "${fixtureKey}" ` +
        `(single-file fixture, no 360 output available)`,
    );
  }

  const profileFile = join(dir, "expected_profile_360.json");
  const campaignFile = join(dir, "expected_campaign_360.json");
  const commsFile = join(dir, "expected_communications_360.json");

  const [profileRaw, campaignRaw, commsRaw] = await Promise.all([
    readJSONFile(profileFile, `expected_profile_360.json for "${fixtureKey}"`),
    readJSONFile(campaignFile, `expected_campaign_360.json for "${fixtureKey}"`),
    readJSONFile(commsFile, `expected_communications_360.json for "${fixtureKey}"`),
  ]);

  return {
    profile: profileRaw as Record<string, unknown>,
    campaign: campaignRaw as Record<string, unknown>,
    communications: commsRaw as unknown as Record<string, unknown>[],
  };
}

/**
 * Load expected lens output for a fixture key.
 */
export async function loadExpectedLensOutput(
  fixtureKey: string,
): Promise<Record<string, unknown>> {
  const dir = findFixtureDir(fixtureKey);

  if (dir.endsWith(".json")) {
    throw new Error(
      `Cannot load lens output for SDK event key "${fixtureKey}" ` +
        `(single-file fixture, no lens output available)`,
    );
  }

  const file = join(dir, "expected_lens_output.json");
  return readJSONFile(file, `expected_lens_output.json for "${fixtureKey}"`);
}

// ─────────────────────────────────────────────
//  Legacy (scenario + domain) API — preserved for backward compat
// ─────────────────────────────────────────────

/** Load raw input fixture for a given scenario + domain. */
export async function loadRawFixtureLegacy(
  scenario: string,
  domain: string,
): Promise<Record<string, unknown>> {
  const file = join(fixturesDir(), domain, "raw_input.json");
  return readJSONFile(file, `raw_input.json for ${domain}`);
}

/** Load expected normalized fixture for a given scenario + domain. */
export async function loadExpectedNormalizedLegacy(
  scenario: string,
  domain: string,
): Promise<Record<string, unknown>> {
  const file = join(fixturesDir(), domain, "expected_normalized.json");
  return readJSONFile(file, `expected_normalized.json for ${domain}`);
}

/** Load graph fixture (nodes + edges) for a domain. */
export async function loadGraphFixtureLegacy(
  domain: string,
): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const nodesFile = join(fixturesDir(), domain, "expected_graph_nodes.json");
  const edgesFile = join(fixturesDir(), domain, "expected_graph_edges.json");

  const [nodesRaw, edgesRaw] = await Promise.all([
    readJSONFile(nodesFile, `expected_graph_nodes.json for ${domain}`),
    readJSONFile(edgesFile, `expected_graph_edges.json for ${domain}`),
  ]);

  return {
    nodes: (nodesRaw as unknown) as GraphNode[],
    edges: (edgesRaw as unknown) as GraphEdge[],
  };
}

/** Load lens output fixture for a domain. */
export async function loadLensFixtureLegacy(
  domain: string,
): Promise<LensOutput> {
  const file = join(fixturesDir(), domain, "expected_lens_output.json");
  const raw = await readJSONFile(file, `expected_lens_output.json for ${domain}`);
  return (raw as unknown) as LensOutput;
}

/** Load 360-view fixtures (profile + campaign + communications) for a domain. */
export async function load360FixtureLegacy(
  domain: string,
): Promise<{
  profile: ProfileIdentity;
  campaign: Campaign;
  communications: Communication[];
}> {
  const profileFile = join(fixturesDir(), domain, "expected_profile_360.json");
  const campaignFile = join(fixturesDir(), domain, "expected_campaign_360.json");
  const commsFile = join(fixturesDir(), domain, "expected_communications_360.json");

  const [profileRaw, campaignRaw, commsRaw] = await Promise.all([
    readJSONFile(profileFile, `expected_profile_360.json for ${domain}`),
    readJSONFile(campaignFile, `expected_campaign_360.json for ${domain}`),
    readJSONFile(commsFile, `expected_communications_360.json for ${domain}`),
  ]);

  return {
    profile: (profileRaw as unknown) as ProfileIdentity,
    campaign: (campaignRaw as unknown) as Campaign,
    communications: (commsRaw as unknown) as Communication[],
  };
}

// ─────────────────────────────────────────────
//  internal helpers
// ─────────────────────────────────────────────

async function readJSONFile(
  filePath: string,
  label: string,
): Promise<Record<string, unknown>> {
  try {
    const raw = await readFile(filePath, "utf-8");
    return JSON.parse(raw);
  } catch (err: any) {
    if (err?.code === "ENOENT") {
      const suggestion = await buildNotFoundSuggestion(filePath, label);
      throw new Error(`Fixture file not found: ${filePath} (${label}). ${suggestion}`);
    }
    throw new Error(
      `Failed to read/parse fixture ${label} at ${filePath}: ${err.message}`,
    );
  }
}

/**
 * When a file is not found, enumerate what IS available in that
 * directory so the error message is actionable.
 */
async function buildNotFoundSuggestion(
  filePath: string,
  label: string,
): Promise<string> {
  // filePath looks like .../fixtures/<domain>/<filename>.json
  // or .../fixtures/<domain>/<filename>.json (for single-file SDK events)
  const parts = filePath.split("/");
  // Try to find the domain directory: it's the second-to-last part
  // when the path ends in .../<domain>/<file>.json
  const domainIdx = parts.length - 2;
  const domain = parts[domainIdx];
  const fixtureDir = join(fixturesDir(), domain);

  try {
    const entries = await readdir(fixtureDir);
    const jsonFiles = entries
      .filter((e) => e.endsWith(".json"))
      .map((e) => `  - ${e}`);
    if (jsonFiles.length === 0) {
      return `Directory "${fixtureDir}" exists but contains no .json files.`;
    }
    return `Available fixtures in "${domain}/":\n${jsonFiles.join("\n")}`;
  } catch {
    return `Directory "${fixtureDir}" could not be read.`;
  }
}
