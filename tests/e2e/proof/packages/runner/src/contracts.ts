// @aether/proof-runner — proof step contracts
import type {
  EventEnvelope,
  HeartbeatPayload,
  IdentifyEventPayload,
  ConversionEventPayload,
  TrackEventPayload,
  SourceClassification,
  ProfileIdentity,
  Campaign,
  Communication,
  Conversion,
  AttributionCredit,
  GraphNode,
  GraphEdge,
  Graph,
  LensInput,
  LensOutput,
  Surface360Query,
  ExplanationEnvelope,
  Journey,
  ConnectorSyncState,
  IdentityEvidenceBundle,
} from "@aether/proof-contracts";

// ---------------------------------------------------------------------------
// ProofContext — passed to every step function
// ---------------------------------------------------------------------------

/** Context available to every proof step at execution time. */
export interface ProofContext {
  /** Tenant identifier under test. */
  readonly tenantId: string;
  /** Workspace identifier under test. */
  readonly workspaceId: string;
  /** Platform under test (web | mobile | shopify | stripe | email | …). */
  readonly platformId: string;
  /** Environment under test. */
  readonly environment: "development" | "staging" | "production";
  /** Pre-loaded fixture data keyed by fixture name. */
  readonly fixtures: Record<string, unknown>;
  /** Access to proof-fixtures loader functions. */
  readonly fixtureLoader: {
    readonly loadRawFixture: (
      key: string,
    ) => Promise<Record<string, unknown>>;
    readonly loadExpectedNormalized: (
      key: string,
    ) => Promise<Record<string, unknown>>;
    readonly loadExpectedGraphOutputs: (
      key: string,
    ) => Promise<{ nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] }>;
    readonly loadExpected360Outputs: (
      key: string,
    ) => Promise<{
      profile: Record<string, unknown>;
      campaign: Record<string, unknown>;
      communications: Record<string, unknown>[];
    }>;
    readonly loadExpectedLensOutput: (
      key: string,
    ) => Promise<Record<string, unknown>>;
    readonly listAvailableFixtures: (
      domainDir: string,
    ) => Promise<string[]>;
  };
}

// ---------------------------------------------------------------------------
// Contract — what each of the 24 proof steps validates
// ---------------------------------------------------------------------------

export interface ProofStepContract {
  /** Canonical step name (must match one of the 24 defined steps). */
  readonly name: string;
  /** Human-readable description of what this step proves. */
  readonly description: string;
  /** Data required before this step can run (keys into ProofContext.fixtures). */
  readonly requires: readonly string[];
  /** Validation function the step must satisfy.
   *
   * Returns `true` when the step's pass criteria are met given the context
   * and any step-specific result data produced by the step function.
   */
  readonly validate: (
    ctx: ProofContext,
    stepResult: Record<string, unknown>,
  ) => boolean | Promise<boolean>;
  /** Optional hint shown when the step is skipped. */
  readonly skipIf?: (ctx: ProofContext) => boolean | Promise<boolean>;
}

// --- 1. tenantProvisioning ---

export const tenantProvisioningContract: ProofStepContract = {
  name: "tenantProvisioning",
  description:
    "Validates that the Aether tenant was provisioned and is reachable via the platform API.",
  requires: [],
  validate: (ctx, result) => {
    return (
      Boolean(result["tenantId"]) &&
      String(result["tenantId"]) === ctx.tenantId &&
      Boolean(result["provisionedAt"])
    );
  },
};

// --- 2. workspaceProvisioning ---

export const workspaceProvisioningContract: ProofStepContract = {
  name: "workspaceProvisioning",
  description:
    "Validates that the proof workspace was created inside the tenant and is active.",
  requires: ["tenantProvisioning"],
  validate: (ctx, result) => {
    return (
      Boolean(result["workspaceId"]) &&
      String(result["workspaceId"]) === ctx.workspaceId &&
      Boolean(result["workspaceStatus"]) &&
      String(result["workspaceStatus"]) === "active"
    );
  },
};

// --- 3. platformRegistration ---

export const platformRegistrationContract: ProofStepContract = {
  name: "platformRegistration",
  description:
    "Validates that the target platform (web | mobile | shopify | stripe | …) is registered against the workspace.",
  requires: ["workspaceProvisioning"],
  validate: (ctx, result) => {
    return (
      Boolean(result["registeredPlatform"]) &&
      String(result["registeredPlatform"]) === ctx.platformId &&
      Boolean(result["registrationStatus"]) &&
      String(result["registrationStatus"]) === "connected"
    );
  },
};

// --- 4. sdkKeyGeneration ---

export const sdkKeyGenerationContract: ProofStepContract = {
  name: "sdkKeyGeneration",
  description:
    "Validates that an SDK write key was generated for the workspace and matches the expected shape.",
  requires: ["platformRegistration"],
  validate: (ctx, result) => {
    const key = result["sdkKey"];
    return (
      typeof key === "string" &&
      key.length > 0 &&
      Boolean(result["keyType"]) &&
      (String(result["keyType"]) === "write" ||
        String(result["keyType"]) === "secret")
    );
  },
};

// --- 5. sdkHeartbeat ---

export const sdkHeartbeatContract: ProofStepContract = {
  name: "sdkHeartbeat",
  description:
    "Validates that the SDK heartbeat payload conforms to HeartbeatPayload and reports status alive.",
  requires: ["sdkKeyGeneration"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const hb = result["heartbeat"];
    if (!hb || typeof hb !== "object") return false;
    return (
      typeof (hb as HeartbeatPayload).timestamp === "number" &&
      typeof (hb as HeartbeatPayload).sessionId === "string" &&
      typeof (hb as HeartbeatPayload).agentId === "string" &&
      (hb as HeartbeatPayload).status === "alive"
    );
  },
};

// --- 6. webEventIngestion ---

export const webEventIngestionContract: ProofStepContract = {
  name: "webEventIngestion",
  description:
    "Validates that a web track/page event was ingested and stored with the expected envelope shape.",
  requires: ["sdkHeartbeat"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const envelope = result["envelope"];
    if (!envelope || typeof envelope !== "object") return false;
    return (
      String((envelope as EventEnvelope).tenant_id) === ctx.tenantId &&
      String((envelope as EventEnvelope).workspace_id) === ctx.workspaceId &&
      String((envelope as EventEnvelope).platform_id) === "web" &&
      Array.isArray((envelope as EventEnvelope).identity) === false &&
      Boolean((envelope as EventEnvelope).identity?.anonymous_id)
    );
  },
};

// --- 7. identifyEventIngestion ---

export const identifyEventIngestionContract: ProofStepContract = {
  name: "identifyEventIngestion",
  description:
    "Validates that an identify event was ingested and stores user traits.",
  requires: ["webEventIngestion"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const payload = result["identifyPayload"];
    if (!payload || typeof payload !== "object") return false;
    return (
      typeof (payload as IdentifyEventPayload).userId === "string" &&
      (payload as IdentifyEventPayload).userId.length > 0 &&
      Boolean((payload as IdentifyEventPayload).traits)
    );
  },
};

// --- 8. conversionIngestion ---

export const conversionIngestionContract: ProofStepContract = {
  name: "conversionIngestion",
  description:
    "Validates that a conversion (monetizable event) was ingested with value and currency.",
  requires: ["identifyEventIngestion"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const conversion = result["conversion"];
    if (!conversion || typeof conversion !== "object") return false;
    return (
      typeof (conversion as ConversionEventPayload).conversionId === "string" &&
      typeof (conversion as ConversionEventPayload).value === "number" &&
      (conversion as ConversionEventPayload).value > 0 &&
      typeof (conversion as ConversionEventPayload).currency === "string"
    );
  },
};

// --- 9. connectorFixtureImport ---

export const connectorFixtureImportContract: ProofStepContract = {
  name: "connectorFixtureImport",
  description:
    "Validates that connector fixtures (e.g. Shopify / Stripe) were imported and sync state is success.",
  requires: ["conversionIngestion"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const syncState = result["syncState"];
    if (!syncState || typeof syncState !== "object") return false;
    return (
      Boolean((syncState as ConnectorSyncState).connector_id) &&
      (syncState as ConnectorSyncState).status === "success" &&
      Boolean((syncState as ConnectorSyncState).is_connected)
    );
  },
};

// --- 10. webhookReplay ---

export const webhookReplayContract: ProofStepContract = {
  name: "webhookReplay",
  description:
    "Validates that a webhook delivery was replayed end-to-end and the downstream event arrived.",
  requires: ["connectorFixtureImport"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    return (
      Boolean(result["replayed"]) && Boolean(result["deliveryId"]) && Boolean(result["receivedAt"])
    );
  },
};

// --- 11. rawEvidenceStorage ---

export const rawEvidenceStorageContract: ProofStepContract = {
  name: "rawEvidenceStorage",
  description:
    "Validates that raw event evidence is durably stored and retrievable by event id.",
  requires: ["webhookReplay"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    return (
      Boolean(result["storageId"]) &&
      Boolean(result["storedEvent"]) &&
      typeof result["storedEvent"] === "object"
    );
  },
};

// --- 12. normalization ---

export const normalizationContract: ProofStepContract = {
  name: "normalization",
  description:
    "Validates that raw events are normalized into the canonical EventEnvelope shape.",
  requires: ["rawEvidenceStorage"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const normalized = result["normalizedEnvelope"];
    if (!normalized || typeof normalized !== "object") return false;
    return (
      Boolean((normalized as EventEnvelope).tenant_id) &&
      Boolean((normalized as EventEnvelope).event_type) &&
      Boolean((normalized as EventEnvelope).timestamp)
    );
  },
};

// --- 13. identityResolution ---

export const identityResolutionContract: ProofStepContract = {
  name: "identityResolution",
  description:
    "Validates that identity resolution merged evidence into a single IdentityEvidenceBundle.",
  requires: ["normalization"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const bundle = result["identityBundle"];
    if (!bundle || typeof bundle !== "object") return false;
    return (
      Boolean((bundle as IdentityEvidenceBundle).user_id) &&
      Array.isArray((bundle as IdentityEvidenceBundle).evidence) &&
      (bundle as IdentityEvidenceBundle).evidence.length > 0
    );
  },
};

// --- 14. profileWrite ---

export const profileWriteContract: ProofStepContract = {
  name: "profileWrite",
  description:
    "Validates that a consolidated ProfileIdentity was written to the profile store.",
  requires: ["identityResolution"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const profile = result["profile"];
    if (!profile || typeof profile !== "object") return false;
    return (
      Boolean((profile as ProfileIdentity).user_id) &&
      Boolean((profile as ProfileIdentity).email) &&
      Array.isArray((profile as ProfileIdentity).identity_sources) &&
      (profile as ProfileIdentity).identity_sources.length > 0
    );
  },
};

// --- 15. journeyWrite ---

export const journeyWriteContract: ProofStepContract = {
  name: "journeyWrite",
  description:
    "Validates that a Journey was written with at least one step and status.",
  requires: ["profileWrite"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const journey = result["journey"];
    if (!journey || typeof journey !== "object") return false;
    return (
      Boolean((journey as Journey).journey_id) &&
      Boolean((journey as Journey).name) &&
      Array.isArray((journey as Journey).steps) &&
      (journey as Journey).steps.length > 0
    );
  },
};

// --- 16. campaignResolution ---

export const campaignResolutionContract: ProofStepContract = {
  name: "campaignResolution",
  description:
    "Validates that campaign resolution matched a user to at least one active Campaign.",
  requires: ["journeyWrite"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const campaigns = result["resolvedCampaigns"];
    if (!Array.isArray(campaigns) || campaigns.length === 0) return false;
    return campaigns.every(
      (c): c is Campaign =>
        Boolean(c) &&
        typeof c === "object" &&
        Boolean((c as Campaign).campaign_id) &&
        Boolean((c as Campaign).name),
    );
  },
};

// --- 17. valueAttachment ---

export const valueAttachmentContract: ProofStepContract = {
  name: "valueAttachment",
  description:
    "Validates that financial/value data was attached to the profile.",
  requires: ["campaignResolution"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const value = result["attachedValue"];
    if (!value || typeof value !== "object") return false;
    return (
      typeof (value as { amount: number }).amount === "number" &&
      (value as { amount: number }).amount >= 0 &&
      typeof (value as { currency: string }).currency === "string"
    );
  },
};

// --- 18. graphNodeWrite ---

export const graphNodeWriteContract: ProofStepContract = {
  name: "graphNodeWrite",
  description:
    "Validates that a GraphNode was written to the entity graph.",
  requires: ["valueAttachment"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const node = result["graphNode"];
    if (!node || typeof node !== "object") return false;
    return (
      Boolean((node as GraphNode).node_id) &&
      Boolean((node as GraphNode).type) &&
      Array.isArray((node as GraphNode).labels) &&
      (node as GraphNode).labels.length > 0
    );
  },
};

// --- 19. graphEdgeWrite ---

export const graphEdgeWriteContract: ProofStepContract = {
  name: "graphEdgeWrite",
  description:
    "Validates that a GraphEdge linking two nodes was written.",
  requires: ["graphNodeWrite"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const edge = result["graphEdge"];
    if (!edge || typeof edge !== "object") return false;
    return (
      Boolean((edge as GraphEdge).edge_id) &&
      Boolean((edge as GraphEdge).source) &&
      Boolean((edge as GraphEdge).target) &&
      Boolean((edge as GraphEdge).relation)
    );
  },
};

// --- 20. profile360Query ---

export const profile360QueryContract: ProofStepContract = {
  name: "profile360Query",
  description:
    "Validates that a Profile 360 query returns a complete profile view.",
  requires: ["graphEdgeWrite"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const view = result["profile360"];
    if (!view || typeof view !== "object") return false;
    return (
      Boolean((view as { user_id: string }).user_id) &&
      Boolean((view as { profile: unknown }).profile) &&
      Boolean((view as { completeness: string }).completeness)
    );
  },
};

// --- 21. campaign360Query ---

export const campaign360QueryContract: ProofStepContract = {
  name: "campaign360Query",
  description:
    "Validates that a Campaign 360 query returns campaign touchpoints and conversions.",
  requires: ["profile360Query"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const view = result["campaign360"];
    if (!view || typeof view !== "object") return false;
    return (
      Boolean((view as { profileId: string }).profileId) &&
      Array.isArray((view as { campaigns: unknown[] }).campaigns) &&
      (view as { campaigns: unknown[] }).campaigns.length > 0
    );
  },
};

// --- 22. communications360Query ---

export const communications360QueryContract: ProofStepContract = {
  name: "communications360Query",
  description:
    "Validates that a Communications 360 query returns the communication timeline.",
  requires: ["campaign360Query"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const view = result["communications360"];
    if (!view || typeof view !== "object") return false;
    return (
      Boolean((view as { profileId: string }).profileId) &&
      Array.isArray((view as { communications: unknown[] }).communications)
    );
  },
};

// --- 23. lensActivation ---

export const lensActivationContract: ProofStepContract = {
  name: "lensActivation",
  description:
    "Validates that a Lens input is accepted and produces a LensOutput with metrics.",
  requires: ["communications360Query"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const output = result["lensOutput"];
    if (!output || typeof output !== "object") return false;
    return (
      Boolean((output as LensOutput).workspace_id) &&
      Boolean((output as LensOutput).lens_name) &&
      Boolean((output as LensOutput).metrics) &&
      (output as LensOutput).metrics !== null
    );
  },
};

// --- 24. explanationProvenance ---

export const explanationProvenanceContract: ProofStepContract = {
  name: "explanationProvenance",
  description:
    "Validates that an ExplanationEnvelope is produced with provenance metadata and completeness.",
  requires: ["lensActivation"],
  validate: (ctx: ProofContext, result: Record<string, unknown>): boolean => {
    const explanation = result["explanation"];
    if (!explanation || typeof explanation !== "object") return false;
    return (
      Boolean((explanation as ExplanationEnvelope).workspace_id) &&
      Boolean((explanation as ExplanationEnvelope).user_id) &&
      Boolean((explanation as ExplanationEnvelope).generated_at) &&
      Boolean(
        (explanation as ExplanationEnvelope).completeness === "complete" ||
          (explanation as ExplanationEnvelope).completeness === "partial" ||
          (explanation as ExplanationEnvelope).completeness === "empty",
      )
    );
  },
};

// ---------------------------------------------------------------------------
// All 24 contracts, in execution order
// ---------------------------------------------------------------------------

export const ALL_PROOF_STEP_CONTRACTS: ProofStepContract[] = [
  tenantProvisioningContract,
  workspaceProvisioningContract,
  platformRegistrationContract,
  sdkKeyGenerationContract,
  sdkHeartbeatContract,
  webEventIngestionContract,
  identifyEventIngestionContract,
  conversionIngestionContract,
  connectorFixtureImportContract,
  webhookReplayContract,
  rawEvidenceStorageContract,
  normalizationContract,
  identityResolutionContract,
  profileWriteContract,
  journeyWriteContract,
  campaignResolutionContract,
  valueAttachmentContract,
  graphNodeWriteContract,
  graphEdgeWriteContract,
  profile360QueryContract,
  campaign360QueryContract,
  communications360QueryContract,
  lensActivationContract,
  explanationProvenanceContract,
];

/** Map from step name → contract for fast lookup. */
export function getContractByName(
  name: string,
): ProofStepContract | undefined {
  return ALL_PROOF_STEP_CONTRACTS.find((c) => c.name === name);
}
