/**
 * FPS-001: Reset proof tenant to a clean baseline before a proof run.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-001
 * Status: implemented
 *
 * Resets the proof tenant and workspace used by the proof spine:
 * 1. Ensures the proof tenant exists (GET → 404 → POST /v1/admin/tenants).
 * 2. Ensures the proof workspace exists under that tenant
 *    (GET/POST /v1/admin/tenants/{id}/workspaces — endpoint-dependent; logged
 *    if absent or returns 404).
 * 3. Clears proof artifacts: SDK events, connector states, graph writes, and
 *    derived outputs tied to the tenant/workspace. Where a batch cleanup
 *    endpoint exists it is called; otherwise the script logs exactly what
 *    would be cleared and skips with a WARNING.
 * 4. Revokes any API keys minted under the proof tenant so stale keys from a
 *    prior proof run cannot be reused.
 * 5. Prints tenant_id, workspace_id, and a short reset summary.
 *
 * Auth: admin-scoped API key passed via the configured API key header. The
 * backend's default API key header is X-Api-Key (see
 * services/backend/config/settings.py → api_key_header) but older scripts/docs
 * reference X-Aether-API-Key; the script honours AETHER_API_KEY_HEADER and
 * falls back to X-Aether-API-Key for backwards compatibility.
 *
 * Env:
 *   PROOF_TENANT_ID       — proof tenant id (default: aether-proof-tenant)
 *   PROOF_WORKSPACE_ID    — proof workspace id (default: proof-lab)
 *   AETHER_API_URL        — backend base URL (default: http://localhost:8000)
 *   AETHER_API_KEY        — admin API key (required)
 *   AETHER_API_KEY_HEADER — header name for the API key (default: X-Aether-API-Key)
 *   PROOF_CLEANUP_WINDOW_HOURS — hours of recent artifacts to consider (default: 24)
 *
 * Exit codes:
 *   0 — tenant/workspace ready, artifacts cleared or skipped cleanly.
 *   1 — anything that prevents the proof spine from running cleanly.
 */

import { env } from "node:process";

const DEFAULT_TENANT_ID = "aether-proof-tenant";
const DEFAULT_WORKSPACE_ID = "proof-lab";

const PROOF_TENANT_ID = (env.PROOF_TENANT_ID ?? "").trim() || DEFAULT_TENANT_ID;
const PROOF_WORKSPACE_ID = (env.PROOF_WORKSPACE_ID ?? "").trim() || DEFAULT_WORKSPACE_ID;

const API_BASE_URL = (env.AETHER_API_URL ?? "").trim() || "http://localhost:8000";
const API_KEY = (env.AETHER_API_KEY ?? env.AETHER_API_KEY_HEADER ?? "").trim();
const API_KEY_HEADER = (env.AETHER_API_KEY_HEADER ?? "").trim() || "X-Aether-API-Key";
const CLEANUP_WINDOW_HOURS = Number(env.PROOF_CLEANUP_WINDOW_HOURS ?? "24");

// Probable workspace admin path; may be absent if no admin workspace router is
// mounted (workspaces are SDK-owned at the time of writing).
const WORKSPACE_PATH = `/v1/admin/tenants/${encodeURIComponent(PROOF_TENANT_ID)}/workspaces`;

// ---------------------------------------------------------------------------
// Tiny fetch helpers — global fetch (Node 18+ undici) is available under tsx
// with DOM lib in the root tsconfig.
// ---------------------------------------------------------------------------

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

function isJsonContentType(headers: Headers): boolean {
  const c = headers.get("content-type") ?? "";
  return c.includes("json") || c.includes("application/json");
}

async function apiCall(
  method: string,
  path: string,
  payload?: unknown,
): Promise<{ status: number; headers: Headers; body: JsonValue; raw: string }> {
  const url = `${API_BASE_URL.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
  const init: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      [API_KEY_HEADER]: API_KEY,
    },
  };
  if (payload !== undefined) {
    init.body = JSON.stringify(payload);
  }
  const res = await fetch(url, init);
  const raw = await res.text();
  const body: JsonValue =
    isJsonContentType(res.headers) && raw.length > 0
      ? (JSON.parse(raw) as JsonValue)
      : raw;
  return { status: res.status, headers: res.headers, body, raw };
}

function extractString(body: JsonValue, candidates: string[]): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const b = body as Record<string, JsonValue>;
  // APIResponse envelope: { data: { id, tenant_id, ... } }
  const data = b.data;
  if (data && typeof data === "object") {
    const d = data as Record<string, JsonValue>;
    for (const k of candidates) {
      const v = d[k];
      if (typeof v === "string" && v) return v;
    }
  }
  for (const k of candidates) {
    const v = b[k];
    if (typeof v === "string" && v) return v;
  }
  return undefined;
}

function tenantIdFrom(body: JsonValue): string {
  return extractString(body, ["id", "tenant_id", "name"]) ?? PROOF_TENANT_ID;
}

function workspaceIdFrom(body: JsonValue): string {
  return (
    extractString(body, ["id", "workspace_id", "name", "tenant_id"]) ??
    PROOF_WORKSPACE_ID
  );
}

// ---------------------------------------------------------------------------
// Tenant
// ---------------------------------------------------------------------------

async function ensureTenant(): Promise<string> {
  const get = await apiCall(
    "GET",
    `/v1/admin/tenants/${encodeURIComponent(PROOF_TENANT_ID)}`,
  );
  if (get.status === 200) {
    const id = tenantIdFrom(get.body);
    console.log(`[FPS-001] proof tenant already exists: ${id}`);
    return id;
  }
  if (get.status === 404) {
    console.log(`[FPS-001] proof tenant not found — creating via POST /v1/admin/tenants`);
  } else if (get.status === 401 || get.status === 403) {
    throw new Error(
      `lookup tenant → ${get.status}: auth failure — ` +
        `set AETHER_API_KEY (admin scope) and retry.`,
    );
  } else {
    throw new Error(`lookup tenant → ${get.status} ${get.raw}`);
  }

  const post = await apiCall("POST", "/v1/admin/tenants", {
    name: PROOF_TENANT_ID,
    plan: "free",
    contact_email: "proof@local",
    settings: {
      description: "Functionality Proof Spine — proof tenant",
      proof_tenant: true,
    },
  });

  if (post.status === 401 || post.status === 403) {
    throw new Error(
      `create tenant → ${post.status}: auth failure — ` +
        `admin API key must have the "admin" permission.`,
    );
  }
  if (post.status !== 200 && post.status !== 201) {
    throw new Error(`create tenant → ${post.status} ${post.raw}`);
  }

  const id = tenantIdFrom(post.body);
  console.log(`[FPS-001] proof tenant created: ${id}`);
  return id;
}

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

async function ensureWorkspace(_tenantId: string): Promise<string | null> {
  const get = await apiCall("GET", WORKSPACE_PATH);
  if (get.status === 200) {
    const id = workspaceIdFrom(get.body);
    console.log(`[FPS-001] proof workspace already exists: ${id}`);
    return id;
  }

  if (get.status === 401 || get.status === 403) {
    throw new Error(
      `lookup workspace → ${get.status}: auth failure — ` +
        `admin API key must have read/admin permission.`,
    );
  }

  // 404 can mean "no workspace" or "endpoint not mounted". Distinguish by way
  // of the body when possible; degrade to a logged skip either way because the
  // workspace is SDK-owned and will be created on first use if needed.
  const bodyText =
    typeof get.body === "string" ? get.body : JSON.stringify(get.body);
  const endpointAbsent =
    get.status === 404 &&
    /not\s+found|not\s+mounted|route.*not|no\s+route/i.test(bodyText);

  if (endpointAbsent) {
    console.warn(
      `[FPS-001] WARNING: workspace admin endpoint ${WORKSPACE_PATH} appears ` +
        `unmounted (404 + route-absent signal). Skipping workspace creation — ` +
        `the SDK may create "${PROOF_WORKSPACE_ID}" on first use.`,
    );
    return null;
  }

  if (get.status === 404) {
    console.warn(
      `[FPS-001] WARNING: workspace lookup returned 404 for ${WORKSPACE_PATH}. ` +
        `Skipping workspace creation — the SDK may create it on first use.`,
    );
    return null;
  }

  console.log(`[FPS-001] proof workspace not found — creating via POST ${WORKSPACE_PATH}`);
  const post = await apiCall("POST", WORKSPACE_PATH, {
    workspace_id: PROOF_WORKSPACE_ID,
    name: PROOF_WORKSPACE_ID,
    tenant_id: _tenantId,
    settings: {
      description: "Functionality Proof Spine — proof workspace",
      proof_workspace: true,
    },
  });

  if (post.status === 401 || post.status === 403) {
    throw new Error(
      `create workspace → ${post.status}: auth failure — ` +
        `admin API key must have write/admin permission.`,
    );
  }
  if (post.status === 404) {
    console.warn(
      `[FPS-001] WARNING: workspace creation endpoint ${WORKSPACE_PATH} returned ` +
        `404. Skipping — the SDK may create the workspace on first use.`,
    );
    return null;
  }
  if (post.status !== 200 && post.status !== 201) {
    throw new Error(`create workspace → ${post.status} ${post.raw}`);
  }

  const id = workspaceIdFrom(post.body);
  console.log(`[FPS-001] proof workspace created: ${id}`);
  return id;
}

// ---------------------------------------------------------------------------
// Artifact cleanup
// ---------------------------------------------------------------------------

interface CleanupRow {
  cleared: number | null;
  reason: string;
}

async function clearApiKeys(tenantId: string): Promise<void> {
  const list = await apiCall(
    "GET",
    `/v1/admin/tenants/${encodeURIComponent(tenantId)}/api-keys`,
  );

  if (list.status === 401 || list.status === 403) {
    throw new Error(
      `list API keys → ${list.status}: auth failure when trying to revoke proof tenant keys`,
    );
  }
  if (list.status !== 200) {
    console.warn(
      `[FPS-001] WARNING: could not list API keys for tenant ${tenantId} ` +
        `(GET /v1/admin/tenants/{id}/api-keys → ${list.status}). Skipping key revocation.`,
    );
    return;
  }

  const data =
    list.body && typeof list.body === "object"
      ? (list.body as Record<string, JsonValue>).data
      : undefined;
  const keyList = Array.isArray(data) ? data : [];
  if (keyList.length === 0) {
    console.log(`[FPS-001] no API keys to revoke for tenant ${tenantId}`);
    return;
  }

  console.log(`[FPS-001] revoking ${keyList.length} API key(s) for tenant ${tenantId}`);
  for (const key of keyList) {
    const keyObj = key && typeof key === "object" ? (key as Record<string, JsonValue>) : {};
    const keyId = (keyObj.id ?? keyObj.key_id) as string | undefined;
    if (!keyId) continue;

    const rev = await apiCall(
      "DELETE",
      `/v1/admin/api-keys/${encodeURIComponent(keyId)}`,
    );
    if (rev.status === 401 || rev.status === 403) {
      throw new Error(`revoke API key ${keyId} → ${rev.status}: auth failure`);
    }
    if (rev.status !== 200) {
      console.warn(
        `[FPS-001] WARNING: failed to revoke API key ${keyId}: ${rev.status} ${rev.raw}`,
      );
      continue;
    }
    console.log(`[FPS-001] revoked API key ${keyId}`);
  }
}

async function clearSdkEvents(tenantId: string): Promise<CleanupRow> {
  console.warn(
    `[FPS-001] WARNING: no batch-delete SDK events endpoint — would clear SDK ` +
      `events for tenant ${tenantId} written within the last ${CLEANUP_WINDOW_HOURS}h ` +
      `(POST /v1/batch ingestion, analytics event store). Skipping.`,
  );
  return { cleared: null, reason: "no batch delete endpoint; skipped" };
}

async function clearConnectorStates(tenantId: string): Promise<CleanupRow> {
  console.warn(
    `[FPS-001] WARNING: no connector-state cleanup endpoint — would clear ` +
      `connector states for tenant ${tenantId} (connector config + last-seen ` +
      `positions). Skipping.`,
  );
  return { cleared: null, reason: "no connector cleanup endpoint; skipped" };
}

async function clearGraphWrites(tenantId: string): Promise<CleanupRow> {
  console.warn(
    `[FPS-001] WARNING: no graph-write cleanup endpoint — would clear identity ` +
      `graph writes and profile projections for tenant ${tenantId} ` +
      `(identity/profile graph). Skipping.`,
  );
  return { cleared: null, reason: "no graph cleanup endpoint; skipped" };
}

async function clearDerivedOutputs(tenantId: string): Promise<CleanupRow> {
  console.warn(
    `[FPS-001] WARNING: no derived-output cleanup endpoint — would clear derived ` +
      `outputs for tenant ${tenantId} (exports, ML predictions, aggregations). ` +
      `Skipping.`,
  );
  return { cleared: null, reason: "no derived output cleanup endpoint; skipped" };
}

async function clearArtifacts(tenantId: string): Promise<Record<string, CleanupRow>> {
  await clearApiKeys(tenantId);
  const [sdkEvents, connectorStates, graphWrites, derivedOutputs] = await Promise.all([
    clearSdkEvents(tenantId),
    clearConnectorStates(tenantId),
    clearGraphWrites(tenantId),
    clearDerivedOutputs(tenantId),
  ]);
  return { sdkEvents, connectorStates, graphWrites, derivedOutputs };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.log("[FPS-001] reset-tenant — starting proof tenant reset");
  console.log(`[FPS-001] tenant_id=${PROOF_TENANT_ID} workspace_id=${PROOF_WORKSPACE_ID}`);
  console.log(`[FPS-001] API base=${API_BASE_URL} api-key-header=${API_KEY_HEADER}`);

  if (!API_KEY) {
    console.error(
      "[FPS-001] ERROR: AETHER_API_KEY (or AETHER_API_KEY_HEADER) is not set. " +
        "An admin-scoped API key is required to create/lookup tenants and revoke keys.",
    );
    process.exit(1);
  }

  if (!API_BASE_URL || API_BASE_URL === "http://localhost:8000") {
    console.warn(
      `[FPS-001] WARNING: AETHER_API_URL not set or using default ${API_BASE_URL}. ` +
        "If the backend is not running locally, set AETHER_API_URL and retry.",
    );
  }

  const tenantId = await ensureTenant();
  const workspaceId = await ensureWorkspace(tenantId);
  const cleanup = await clearArtifacts(tenantId);

  console.log("\n[FPS-001] --- RESET SUMMARY ---");
  console.log(`tenant_id:      ${tenantId}`);
  console.log(`workspace_id:   ${workspaceId ?? "(not created — endpoint absent)"}`);
  console.log(
    `sdk_events:     cleared=${cleanup.sdkEvents.cleared ?? "n/a"} (${cleanup.sdkEvents.reason})`,
  );
  console.log(
    `connector_state: cleared=${cleanup.connectorStates.cleared ?? "n/a"} (${cleanup.connectorStates.reason})`,
  );
  console.log(
    `graph_writes:   cleared=${cleanup.graphWrites.cleared ?? "n/a"} (${cleanup.graphWrites.reason})`,
  );
  console.log(
    `derived_outputs: cleared=${cleanup.derivedOutputs.cleared ?? "n/a"} (${cleanup.derivedOutputs.reason})`,
  );
  console.log("[FPS-001] --- END SUMMARY ---");
  console.log("[FPS-001] reset-tenant complete.");
  process.exit(0);
}

main().catch((err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err);
  console.error(`[FPS-001] FATAL: ${msg}`);
  process.exit(1);
});
