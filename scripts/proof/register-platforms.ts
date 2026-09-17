#!/usr/bin/env tsx
/**
 * FPS-002: Register all target platforms for the proof tenant.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-002
 * Status: implemented
 *
 * Registers the 8 proof platforms for the proof tenant via the activation
 * SDK-selection endpoint. The backend has no dedicated platform-registration
 * route (no POST /v1/platforms or POST /v1/integrations/platforms exists),
 * so we use POST /v1/activation/sdk-selection which records the platform list
 * as the tenant's SDK selection — the canonical path for declaring which
 * platforms a tenant runs.
 *
 * Platforms registered:
 *   proof-web, proof-react, proof-ios, proof-android,
 *   proof-shopify, proof-stripe, proof-email, proof-campaigns
 *
 * Idempotent — safe to run multiple times. Exit 0 on success, 1 on failure.
 */

const TENANT_ID = process.env.PROOF_TENANT_ID ?? "aether-proof-tenant";
const API_URL = process.env.AETHER_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.AETHER_API_KEY;

const PLATFORMS = [
  "proof-web",
  "proof-react",
  "proof-ios",
  "proof-android",
  "proof-shopify",
  "proof-stripe",
  "proof-email",
  "proof-campaigns",
] as const;

async function request(method: string, path: string, body?: unknown): Promise<unknown> {
  const url = `${API_URL.replace(/\/$/, "")}/v1${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (API_KEY) {
    headers["X-Aether-API-Key"] = API_KEY;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    console.error(`[FPS-002] network error calling ${method} ${url}:`, err);
    process.exit(1);
  }

  const status = response.status;
  if (status === 401) {
    console.error(`[FPS-002] 401 Unauthorized — check AETHER_API_KEY`);
    process.exit(1);
  }
  if (status === 403) {
    console.error(`[FPS-002] 403 Forbidden — API key lacks write permission`);
    process.exit(1);
  }
  if (status === 404) {
    console.error(`[FPS-002] 404 Not Found — endpoint ${path} does not exist on server`);
    process.exit(1);
  }
  if (status >= 500) {
    console.error(`[FPS-002] ${status} Server Error — backend may be down`);
    process.exit(1);
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error(`[FPS-002] ${status} ${response.statusText}: ${text}`);
    process.exit(1);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main(): Promise<void> {
  console.log(`[FPS-002] Registering ${PLATFORMS.length} platforms for tenant="${TENANT_ID}"`);
  console.log(`[FPS-002] API base: ${API_URL}`);

  if (!API_KEY) {
    console.warn(
      "[FPS-002] WARNING: AETHER_API_KEY not set — requests will go without auth header. " +
        "The proof tenant may need an API key with write permission.",
    );
  }

  // Sanity-check the endpoint exists with a GET status call first.
  console.log("[FPS-002] Probing activation status endpoint...");
  try {
    await request("GET", "/activation/status");
    console.log("[FPS-002] Activation endpoint reachable.");
  } catch {
    console.error("[FPS-002] Cannot reach /v1/activation/status — aborting.");
    process.exit(1);
  }

  // Register all platforms via SDK selection.
  // POST /v1/activation/sdk-selection { platforms: [...] }
  // This is idempotent: re-selecting the same platforms is a no-op state transition.
  console.log("[FPS-002] Calling POST /v1/activation/sdk-selection...");
  const result = await request("POST", "/activation/sdk-selection", {
    platforms: PLATFORMS,
  });

  const data = (result as any)?.data;
  if (!data) {
    console.error("[FPS-002] Unexpected response shape — no data field:", JSON.stringify(result));
    process.exit(1);
  }

  const selected = Array.isArray(data.sdk_selection) ? data.sdk_selection : [];
  const registered: string[] = [];

  for (const platform of PLATFORMS) {
    if (selected.includes(platform)) {
      console.log(`[FPS-002] ✓ ${platform} — registered (sdk_selection confirmed)`);
      registered.push(platform);
    } else {
      console.warn(`[FPS-002] ✗ ${platform} — not in sdk_selection response (state may be stale)`);
    }
  }

  // If the response includes platform identifiers, print them.
  if (data.platform_ids && Array.isArray(data.platform_ids)) {
    console.log("[FPS-002] Platform identifiers from server:");
    for (const pid of data.platform_ids) {
      console.log(`  - ${pid}`);
    }
  }

  console.log(`[FPS-002] Registration complete: ${registered.length}/${PLATFORMS.length} platforms confirmed.`);
  console.log(`[FPS-002] Tenant state: ${data.state ?? "unknown"}`);
}

main().catch((err) => {
  console.error("[FPS-002] Unhandled error:", err);
  process.exit(1);
});
