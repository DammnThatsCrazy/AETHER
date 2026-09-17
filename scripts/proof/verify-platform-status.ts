#!/usr/bin/env tsx
/**
 * FPS-004: Verify that all registered proof platforms are present and expose
 * the required status fields.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-004
 * Status: implemented
 *
 * Verifies the 8 proof platforms registered for the proof tenant:
 *   SDK platforms:   proof-web, proof-react, proof-ios, proof-android
 *   Connector platforms: proof-shopify, proof-stripe, proof-email, proof-campaigns
 *
 * Strategy:
 *   1. Try GET /v1/admin/tenants/{tenant_id}/platforms
 *   2. Fall back to GET /v1/platforms
 *   3. Fall back to GET /v1/admin/platforms
 *   4. If no list endpoint returns 200, query each platform individually via
 *      GET /v1/platforms/{platform_id}
 *
 * Exit 0 if all 8 platforms are found with the required fields present
 * (null/empty values are acceptable before activity). Exit 1 if any platform
 * is missing, any required field is absent, or an API call fails.
 */

const TENANT_ID = process.env.PROOF_TENANT_ID ?? "aether-proof-tenant";
const API_URL = process.env.AETHER_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.AETHER_API_KEY;

// ── Guard: API key is required ───────────────────────────────────────────────

if (!API_KEY) {
  console.error(
    "[FPS-004] ERROR: AETHER_API_KEY environment variable is required but not set.\n" +
      "  Set it to a valid API key with read permission for tenant: " +
      TENANT_ID +
      "\n  Example: export AETHER_API_KEY=ak_...",
  );
  process.exit(1);
}

// ── Proof platform definitions ───────────────────────────────────────────────

const SDK_PLATFORMS = [
  { id: "proof-web", expectedType: "web" },
  { id: "proof-react", expectedType: "react" },
  { id: "proof-ios", expectedType: "ios" },
  { id: "proof-android", expectedType: "android" },
] as const;

const CONNECTOR_PLATFORMS = [
  { id: "proof-shopify", expectedType: "ecommerce" },
  { id: "proof-stripe", expectedType: "payments" },
  { id: "proof-email", expectedType: "email" },
  { id: "proof-campaigns", expectedType: "campaigns" },
] as const;

const ALL_PLATFORMS = [...SDK_PLATFORMS, ...CONNECTOR_PLATFORMS] as const;

const REQUIRED_FIELDS = [
  "platform_id",
  "platform_type",
  "environment",
  "sdk_key_status",
  "connector_status",
  "last_seen_at",
  "last_heartbeat_at",
  "last_sync_at",
  "last_error",
  "degraded_reason",
] as const;

// ── HTTP helper ──────────────────────────────────────────────────────────────

async function request(
  method: string,
  path: string,
  body?: unknown,
): Promise<unknown> {
  const url = `${API_URL.replace(/\/$/, "")}/v1${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ["X-Aether-API-Key"]: API_KEY,
  };

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    console.error(`[FPS-004] network error calling ${method} ${url}:`, err);
    process.exit(1);
  }

  const status = response.status;

  // ── HTTP error handling ───────────────────────────────────────────────────

  if (status === 401) {
    console.error(
      `[FPS-004] 401 Unauthorized — invalid or missing AETHER_API_KEY. ` +
        `Check that the key is correct and has read permission.`,
    );
    process.exit(1);
  }
  if (status === 403) {
    console.error(
      `[FPS-004] 403 Forbidden — API key lacks permission to read platform status. ` +
        `The key needs at least 'read' permission.`,
    );
    process.exit(1);
  }
  if (status === 404) {
    // 404 is handled by the caller — it means the endpoint doesn't exist.
    const text = await response.text().catch(() => "");
    return { _fps_404: true, _fps_404_body: text };
  }
  if (status === 429) {
    console.error(
      `[FPS-004] 429 Too Many Requests — rate limit exceeded. ` +
        `Wait and retry, or check the backend rate-limit configuration.`,
    );
    process.exit(1);
  }
  if (status >= 500) {
    console.error(
      `[FPS-004] ${status} Server Error — the backend may be down or unhealthy. ` +
        `Check that the server is running at ${API_URL}.`,
    );
    process.exit(1);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error(
      `[FPS-004] ${status} ${response.statusText}: ${text || method} ${path}`,
    );
    process.exit(1);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

// ── Response extractors ──────────────────────────────────────────────────────

/** Try to extract an array of platform objects from a response of unknown shape. */
function extractPlatformList(data: unknown): unknown[] | null {
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    for (const key of ["platforms", "items", "data", "results", "records"]) {
      const v = d[key];
      if (Array.isArray(v)) return v;
    }
    // Nested envelope: { data: { platforms: [...] } }
    const nested = d.data;
    if (nested && typeof nested === "object") {
      const nd = nested as Record<string, unknown>;
      for (const key of ["platforms", "items", "data", "results", "records"]) {
        const v = nd[key];
        if (Array.isArray(v)) return v;
      }
      // { data: { data: [...] } }
      if (Array.isArray(nd.data)) return nd.data;
    }
  }
  return null;
}

/** Try to extract a single platform object from a response of unknown shape. */
function extractPlatformItem(data: unknown): Record<string, unknown> | null {
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    // Direct object with platform fields
    if (d.platform_id !== undefined || d.platform_type !== undefined) {
      return d as Record<string, unknown>;
    }
    // { data: { platform: {...} } } or { data: {...} }
    if (d.data && typeof d.data === "object") {
      const nd = d.data as Record<string, unknown>;
      if (nd.platform && typeof nd.platform === "object") {
        const p = nd.platform as Record<string, unknown>;
        if (p.platform_id !== undefined || p.platform_type !== undefined) {
          return p;
        }
      }
      if (nd.platform_id !== undefined || nd.platform_type !== undefined) {
        return nd;
      }
    }
    // { platform: {...} }
    if (d.platform && typeof d.platform === "object") {
      const p = d.platform as Record<string, unknown>;
      if (p.platform_id !== undefined || p.platform_type !== undefined) {
        return p;
      }
    }
  }
  return null;
}

// ── Platform fetching ────────────────────────────────────────────────────────

/**
 * Try to fetch the full platform list from the backend. Returns the list of
 * platform objects, or null if no list endpoint is available.
 */
async function fetchPlatformList(): Promise<Record<string, unknown>[] | null> {
  const endpoints = [
    `/admin/tenants/${TENANT_ID}/platforms`,
    `/platforms`,
    `/admin/platforms`,
  ];

  for (const path of endpoints) {
    console.log(`[FPS-004] Trying list endpoint: GET /v1${path} ...`);
    const result = await request("GET", path);
    if ((result as Record<string, unknown>)?._fps_404) {
      console.log(`[FPS-004]   → 404, endpoint does not exist.`);
      continue;
    }
    const list = extractPlatformList(result);
    if (list && list.length > 0) {
      console.log(
        `[FPS-004]   → got ${list.length} platform(s) from GET /v1${path}.`,
      );
      return list as Record<string, unknown>[];
    }
    // Endpoint exists but returned empty or unexpected shape — try next.
    console.log(`[FPS-004]   → no platform list found in response, trying next.`);
  }

  return null;
}

/**
 * Fetch a single platform by ID. Returns the platform object, or null if not found.
 */
async function fetchPlatformById(
  platformId: string,
): Promise<Record<string, unknown> | null> {
  const path = `/platforms/${platformId}`;
  console.log(`[FPS-004] Fetching individual platform: GET /v1${path} ...`);
  const result = await request("GET", path);

  if ((result as Record<string, unknown>)?._fps_404) {
    console.log(`[FPS-004]   → 404, platform not found.`);
    return null;
  }

  const item = extractPlatformItem(result);
  if (item && (item.platform_id !== undefined || item.platform_type !== undefined)) {
    console.log(`[FPS-004]   → found platform: ${item.platform_id}`);
    return item;
  }

  // Unexpected response shape — treat as not found.
  console.log(
    `[FPS-004]   → unexpected response shape, cannot extract platform record.`,
  );
  return null;
}

// ── Verification logic ───────────────────────────────────────────────────────

interface VerificationResult {
  platformId: string;
  expectedType: string;
  found: boolean;
  record: Record<string, unknown> | null;
  missingFields: string[];
  typeMismatch: boolean;
  status: "PASS" | "FAIL";
  reasons: string[];
}

function verifyPlatform(
  platformId: string,
  expectedType: string,
  record: Record<string, unknown> | null,
): VerificationResult {
  const reasons: string[] = [];
  const missingFields: string[] = [];

  if (!record) {
    return {
      platformId,
      expectedType,
      found: false,
      record: null,
      missingFields: [...REQUIRED_FIELDS],
      typeMismatch: false,
      status: "FAIL",
      reasons: [`Platform "${platformId}" not found in backend`],
    };
  }

  // Check required fields are present (null/empty values are OK — they're
  // expected before any activity has occurred).
  for (const field of REQUIRED_FIELDS) {
    if (!(field in record)) {
      missingFields.push(field);
    }
  }

  // Check platform_type matches expected type.
  const actualType = (record["platform_type"] as string | undefined);
  const typeMismatch =
    actualType !== undefined && actualType !== expectedType;

  const found = missingFields.length === 0;

  if (!found) {
    reasons.push(
      `Platform "${platformId}" missing required fields: ${missingFields.join(", ")}`,
    );
  }

  if (typeMismatch) {
    reasons.push(
      `Platform "${platformId}" has platform_type="${actualType}" ` +
        `but expected "${expectedType}"`,
    );
  }

  // SDK platforms must have a platform_type matching the expected SDK type.
  // Connector platforms must have a platform_type matching the expected connector type.

  return {
    platformId,
    expectedType,
    found: missingFields.length === 0 && !typeMismatch,
    record,
    missingFields,
    typeMismatch,
    status: found ? "PASS" : "FAIL",
    reasons,
  };
}

// ── Status table printing ────────────────────────────────────────────────────

function truncate(str: unknown, maxLen = 20): string {
  const s = str === undefined ? "undefined" : str === null ? "null" : String(str);
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 3) + "...";
}

function printStatusTable(results: VerificationResult[]): void {
  const header = [
    "PLATFORM",
    "TYPE",
    "ENV",
    "SDK_KEY",
    "CONN",
    "LAST_SEEN",
    "HEARTBEAT",
    "SYNC",
    "ERROR",
    "DEGRADED",
    "STATUS",
  ].join(" | ");

  const sep = "-".repeat(header.length);

  console.log("\n" + sep);
  console.log(`  Platform Status — Tenant: ${TENANT_ID}`);
  console.log(sep);

  console.log(header);
  console.log(sep);

  for (const r of results) {
    const rec = r.record;
    const row = [
      truncate(r.platformId, 14),
      truncate(rec?.["platform_type"] ?? "—", 10),
      truncate(rec?.["environment"] ?? "—", 6),
      truncate(rec?.["sdk_key_status"] ?? "—", 10),
      truncate(rec?.["connector_status"] ?? "—", 8),
      truncate(rec?.["last_seen_at"] ?? "—", 18),
      truncate(rec?.["last_heartbeat_at"] ?? "—", 18),
      truncate(rec?.["last_sync_at"] ?? "—", 18),
      truncate(rec?.["last_error"] ?? "—", 14),
      truncate(rec?.["degraded_reason"] ?? "—", 10),
      r.status,
    ].join(" | ");

    console.log(row);
  }

  console.log(sep);
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  console.log(`[FPS-004] Verifying platform status for tenant="${TENANT_ID}"`);
  console.log(`[FPS-004] API base: ${API_URL}`);
  console.log(`[FPS-004] Platforms to verify: ${ALL_PLATFORMS.length}`);

  // Step 1: Try to get the platform list from a list endpoint.
  let platformList: Record<string, unknown>[] | null = null;

  platformList = await fetchPlatformList();

  // Step 2: If no list endpoint worked, fall back to individual queries.
  let usedIndividualFallback = false;

  if (!platformList) {
    console.log(
      "[FPS-004] No platform list endpoint available. Falling back to individual queries.",
    );
    usedIndividualFallback = true;
  }

  // Step 3: Verify each of the 8 proof platforms.
  const results: VerificationResult[] = [];

  for (const platform of ALL_PLATFORMS) {
    let record: Record<string, unknown> | null = null;

    if (platformList) {
      // Look up the platform in the list response.
      record = platformList.find(
        (p) =>
          String(p.platform_id) === platform.id ||
          String(p.id) === platform.id ||
          String(p.platform) === platform.id,
      ) ?? null;
    }

    if (!record && usedIndividualFallback) {
      // Fetch individual platform by ID.
      record = await fetchPlatformById(platform.id);
    }

    const result = verifyPlatform(platform.id, platform.expectedType, record);
    results.push(result);
  }

  // Step 4: Print the status table.
  printStatusTable(results);

  // Step 5: Report failures.
  const failures = results.filter((r) => r.status === "FAIL");

  if (failures.length > 0) {
    console.log(`\n[FPS-004] FAIL — ${failures.length}/${ALL_PLATFORMS.length} platform(s) have issues:\n`);
    for (const f of failures) {
      for (const reason of f.reasons) {
        console.log(`  ✗ ${f.platformId}: ${reason}`);
      }
    }
    console.log(`\n[FPS-004] Verification FAILED. ${failures.length} platform(s) require attention.`);
    process.exit(1);
  }

  // Step 6: All platforms passed.
  const passed = results.filter((r) => r.status === "PASS").length;
  console.log(
    `\n[FPS-004] Verification PASSED — all ${passed}/${ALL_PLATFORMS.length} platforms ` +
      `registered with required fields present.`,
  );
  process.exit(0);
}

main().catch((err) => {
  console.error("[FPS-004] Unhandled error:", err);
  process.exit(1);
});
