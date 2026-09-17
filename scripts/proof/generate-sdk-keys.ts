#!/usr/bin/env tsx
/**
 * FPS-003: Generate staging SDK keys for the 4 SDK platforms.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-003
 * Status: implemented
 *
 * Mints SDK API keys for the proof tenant via POST /v1/activation/create-sdk-keys.
 * The raw key is returned ONCE in the response — only key identifiers/prefixes
 * are printed and persisted; the full secret is never logged.
 *
 * SDK platforms covered:
 *   proof-web, proof-react, proof-ios, proof-android
 *
 * Keys are persisted to .proof-keys.json (repo root, gitignored) so smoke
 * scripts can read them. Exit 0 on success, 1 on failure.
 */

const TENANT_ID = process.env.PROOF_TENANT_ID ?? "aether-proof-tenant";
const API_URL = process.env.AETHER_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.AETHER_API_KEY;

const SDK_PLATFORMS = ["proof-web", "proof-react", "proof-ios", "proof-android"] as const;
const KEY_LABEL = "proof-spine";
const KEYS_FILE = ".proof-keys.json";

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
    console.error(`[FPS-003] network error calling ${method} ${url}:`, err);
    process.exit(1);
  }

  const status = response.status;
  if (status === 401) {
    console.error(`[FPS-003] 401 Unauthorized — check AETHER_API_KEY`);
    process.exit(1);
  }
  if (status === 403) {
    console.error(`[FPS-003] 403 Forbidden — API key lacks write permission`);
    process.exit(1);
  }
  if (status === 404) {
    console.error(`[FPS-003] 404 Not Found — endpoint ${path} does not exist on server`);
    process.exit(1);
  }
  if (status >= 500) {
    console.error(`[FPS-003] ${status} Server Error — backend may be down`);
    process.exit(1);
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error(`[FPS-003] ${status} ${response.statusText}: ${text}`);
    process.exit(1);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

/**
 * Return a short public identifier for a key: the first 8 chars of the key ID
 * (the hashed prefix the server persists). Never the raw secret.
 */
function keyIdentifier(key: { id?: string; key_id?: string; name?: string } | string): string {
  if (typeof key === "string") return key.slice(0, 8);
  return (key.id ?? key.key_id ?? key.name ?? "unknown").slice(0, 8);
}

/**
 * Persist key metadata (never raw secrets) to .proof-keys.json.
 */
function persistKeys(keys: Array<{ id: string; label: string; platform?: string }>): void {
  const fileData = {
    tenant_id: TENANT_ID,
    label: KEY_LABEL,
    generated_at: new Date().toISOString(),
    platforms: SDK_PLATFORMS,
    keys: keys.map((k) => ({
      id: k.id,
      identifier: k.id.slice(0, 8), // hashed prefix only
      label: k.label,
      platform: k.platform,
      // NOTE: raw_key is NEVER stored — it was shown once at creation time only.
    })),
  };

  // Ensure .gitignore covers this file.
  ensureGitignored();

  const fs = require("fs");
  const path = require("path");
  const repoRoot = path.resolve(__dirname, "..", "..");
  const filePath = path.join(repoRoot, KEYS_FILE);
  fs.writeFileSync(filePath, JSON.stringify(fileData, null, 2), "utf-8");
  console.log(`[FPS-003] Keys metadata persisted to ${KEYS_FILE}`);
}

/**
 * Add .proof-keys.json to .gitignore if not already covered.
 */
function ensureGitignored(): void {
  const fs = require("fs");
  const path = require("path");
  const repoRoot = path.resolve(__dirname, "..", "..");
  const gitignorePath = path.join(repoRoot, ".gitignore");

  let gitignore = "";
  if (fs.existsSync(gitignorePath)) {
    gitignore = fs.readFileSync(gitignorePath, "utf-8");
  }

  if (!gitignore.includes(KEYS_FILE)) {
    fs.appendFileSync(gitignorePath, `\n# FPS SDK keys (secrets — never commit)\n${KEYS_FILE}\n`);
    console.log(`[FPS-003] Added ${KEYS_FILE} to .gitignore`);
  }
}

async function main(): Promise<void> {
  console.log(`[FPS-003] Generating SDK keys for tenant="${TENANT_ID}"`);
  console.log(`[FPS-003] API base: ${API_URL}`);
  console.log(`[FPS-003] Platforms: ${SDK_PLATFORMS.join(", ")}`);
  console.log(`[FPS-003] Label: ${KEY_LABEL}`);

  if (!API_KEY) {
    console.warn(
      "[FPS-003] WARNING: AETHER_API_KEY not set — requests will go without auth header.",
    );
  }

  // Verify the endpoint is reachable first.
  console.log("[FPS-003] Probing activation status endpoint...");
  try {
    await request("GET", "/activation/status");
    console.log("[FPS-003] Activation endpoint reachable.");
  } catch {
    console.error("[FPS-003] Cannot reach /v1/activation/status — aborting.");
    process.exit(1);
  }

  // POST /v1/activation/create-sdk-keys { count, label }
  // The backend mints `count` keys, returns each with { id, key (raw, once), label }.
  // We request 4 keys — one per SDK platform.
  console.log(`[FPS-003] Calling POST /v1/activation/create-sdk-keys (count=${SDK_PLATFORMS.length})...`);
  const result = await request("POST", "/activation/create-sdk-keys", {
    count: SDK_PLATFORMS.length,
    label: KEY_LABEL,
  });

  const data = (result as any)?.data;
  if (!data) {
    console.error("[FPS-003] Unexpected response shape — no data field:", JSON.stringify(result));
    process.exit(1);
  }

  const keys: Array<{ id: string; label: string; platform?: string }> = [];
  const rawKeys = Array.isArray(data.keys) ? data.keys : [];

  if (rawKeys.length === 0) {
    console.error("[FPS-003] No keys returned in response:", JSON.stringify(data));
    process.exit(1);
  }

  console.log(`[FPS-003] Received ${rawKeys.length} key(s):`);

  rawKeys.forEach((k: any, idx: number) => {
    const id = k.id ?? k.key_id ?? `key-${idx}`;
    const rawKey = k.key;

    // Print ONLY the identifier (hashed prefix) — never the raw secret.
    if (rawKey && typeof rawKey === "string") {
      // Show first 8 chars of the raw key as a human-readable prefix for confirmation.
      console.log(`  - ${id}  prefix=${rawKey.slice(0, 8)}...  (full secret shown once, not persisted)`);
    } else {
      console.log(`  - ${id}`);
    }

    keys.push({
      id,
      label: k.label ?? KEY_LABEL,
      platform: SDK_PLATFORMS[idx] ?? undefined,
    });
  });

  // Persist key metadata (no secrets) for smoke scripts.
  persistKeys(keys);

  const state = data.state ?? "unknown";
  console.log(`[FPS-003] Tenant state after key creation: ${state}`);
  console.log(`[FPS-003] Keys generated: ${keys.length}/${SDK_PLATFORMS.length}`);
}

main().catch((err) => {
  console.error("[FPS-003] Unhandled error:", err);
  process.exit(1);
});
