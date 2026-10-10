import { createHash } from "crypto";
import { copyFileSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "fs";
import { dirname, isAbsolute, resolve, sep } from "path";

export type EvidenceReference = {
  id: string;
  kind: "contract_inventory" | "scenario_result" | "scenario_artifact" | "graph_versions" | "restatement_job" | "projection_outcome" | "feature_flags" | "ui_e2e" | "ui_e2e_screenshot";
  path: string;
  sha256: string;
};

export type IdentityContinuityPack = {
  schema_version: "1.0.0";
  proof_id: string;
  generated_at: string;
  commit: { sha: string; branch: string };
  environment: { name: "staging"; deployment_id: string; observed_at: string };
  scenario_run: { execution_id: string; tenant_ref: string; deployment_id: string };
  evidence: EvidenceReference[];
  contract_inventory: {
    evidence_id: string;
    required_contract_ids: string[];
    observed_contract_ids: string[];
  };
  scenarios: Array<{
    id: string;
    status: "passed" | "failed" | "skipped";
    evidence_id: string;
    artifact_evidence_id: string;
    evidence_sha256: string;
    execution_ref: string;
    executed_at: string;
  }>;
  graph_versions: Array<{
    tenant_id: string;
    graph: string;
    before: string;
    after: string;
    observed_at: string;
    evidence_id: string;
  }>;
  restatement_jobs: Array<{
    tenant_id: string;
    job_id: string;
    status: "succeeded" | "failed" | "pending";
    projection: string;
    source_graph_version: string;
    resulting_graph_version: string;
    completed_at: string;
    evidence_id: string;
  }>;
  projection_outcomes: Array<{
    projection: string;
    status: "completed" | "unsupported" | "failed";
    evidence_id: string;
  }>;
  feature_flags: {
    evidence_id: string;
    values: Record<string, boolean>;
    required_enabled: string[];
  };
  ui_evidence: Array<{
    id: string;
    surface: "activation" | "review_queue" | "profile_360";
    test_id: string;
    tenant_ref: string;
    deployment_id?: string;
    evidence_class: "ui_fixture_only" | "ui_live_staging";
    api_mode: "playwright_route_fixture" | "authenticated_real_backend";
    live_staging_claim: boolean;
    captured_at: string;
    structured_evidence_id: string;
    screenshot_evidence_id: string;
  }>;
};

export type PackValidation = { valid: boolean; errors: string[] };

export const REQUIRED_IDENTITY_CONTINUITY_SCENARIOS = [
  "A_import_first_sdk_later",
  "B_shared_device_no_merge",
  "C_bad_merge_split",
  "D_agent_human_no_merge",
  "shared_email_review",
  "cross_tenant_block",
  "deleted_suppressed_identity_block",
  "multi_sdk_same_user",
  "connector_reimport_idempotency",
  "projection_restatement",
] as const;

export const REQUIRED_PROJECTION_OUTCOMES = {
  profile_360: "completed",
  journey: "completed",
  campaign_360: "completed",
  communications_360: "completed",
  value: "completed",
  signals: "completed",
  agent_360: "completed",
  execution_360: "completed",
  syndicates: "unsupported",
  account_360: "completed",
} as const;

const nonEmpty = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;
const isoDate = (value: unknown): value is string =>
  nonEmpty(value) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
const unique = (items: string[]): boolean => new Set(items).size === items.length;
const hasSensitiveArtifactValue = (value: unknown): boolean => {
  if (typeof value === "string") {
    const digits = value.replace(/\D/g, "").length;
    return /(?:bearer\s+\S+|(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]+|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/i.test(value)
      || (/^[+\d().\s/-]+$/.test(value) && digits >= 10 && digits <= 15);
  }
  if (Array.isArray(value)) return value.some(hasSensitiveArtifactValue);
  if (value && typeof value === "object") return Object.values(value as Record<string, unknown>).some(hasSensitiveArtifactValue);
  return false;
};

/** Validate both the pack's claims and the bytes of each referenced evidence file. */
export function validateIdentityContinuityPack(
  value: unknown,
  packPath: string
): PackValidation {
  const errors: string[] = [];
  const fail = (message: string): void => { errors.push(message); };
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { valid: false, errors: ["pack must be a JSON object"] };
  }
  const pack = value as Partial<IdentityContinuityPack>;
  if (pack.schema_version !== "1.0.0") fail("schema_version must be 1.0.0");
  if (!nonEmpty(pack.proof_id)) fail("proof_id is required");
  if (!isoDate(pack.generated_at)) fail("generated_at must be an ISO timestamp");
  if (!pack.commit || !/^[0-9a-f]{40,64}$/i.test(pack.commit.sha || "")) fail("commit.sha must be a full git SHA");
  if (!pack.commit || !nonEmpty(pack.commit.branch)) fail("commit.branch is required");
  if (!pack.environment || pack.environment.name !== "staging" || !nonEmpty(pack.environment.deployment_id) || !isoDate(pack.environment.observed_at)) {
    fail("environment must identify a staging deployment and observation timestamp");
  }

  const evidence = Array.isArray(pack.evidence) ? pack.evidence : [];
  if (!evidence.length) fail("evidence must contain at least one collected evidence file");
  const evidenceById = new Map<string, EvidenceReference>();
  const evidencePaths = new Set<string>();
  for (const [index, ref] of evidence.entries()) {
    if (!ref || !nonEmpty(ref.id) || !nonEmpty(ref.path) || !/^[0-9a-f]{64}$/i.test(ref.sha256 || "") || !["contract_inventory", "scenario_result", "scenario_artifact", "graph_versions", "restatement_job", "projection_outcome", "feature_flags", "ui_e2e", "ui_e2e_screenshot"].includes(ref.kind)) {
      fail(`evidence[${index}] requires id, evidence kind, relative path, and SHA-256`);
      continue;
    }
    if (evidenceById.has(ref.id)) fail(`evidence id is duplicated: ${ref.id}`);
    evidenceById.set(ref.id, ref);
    if (evidencePaths.has(ref.path)) fail(`evidence path is duplicated: ${ref.path}`);
    evidencePaths.add(ref.path);
    const base = dirname(resolve(packPath));
    const resolved = resolve(base, ref.path);
    if (isAbsolute(ref.path) || !resolved.startsWith(`${base}${sep}`)) {
      fail(`evidence ${ref.id} path must stay beneath the pack directory`);
      continue;
    }
    try {
      const realBase = realpathSync(base);
      const realEvidencePath = realpathSync(resolved);
      if (!realEvidencePath.startsWith(`${realBase}${sep}`)) {
        fail(`evidence ${ref.id} resolves outside the pack directory`);
        continue;
      }
      const actual = createHash("sha256").update(readFileSync(realEvidencePath)).digest("hex");
      if (actual.toLowerCase() !== ref.sha256.toLowerCase()) fail(`evidence ${ref.id} SHA-256 does not match file bytes`);
    } catch {
      fail(`evidence ${ref.id} file is missing or unreadable: ${ref.path}`);
    }
  }
  const scenarioRun = pack.scenario_run;
  if (!scenarioRun || !nonEmpty(scenarioRun.execution_id) || !nonEmpty(scenarioRun.tenant_ref) || !nonEmpty(scenarioRun.deployment_id)) {
    fail("scenario_run must bind an execution, tenant, and deployment");
  } else if (pack.environment?.deployment_id !== scenarioRun.deployment_id) {
    fail("scenario_run deployment does not match the staging capture deployment");
  }
  const requireEvidence = (id: string | undefined, label: string, expectedKind: EvidenceReference["kind"]): void => {
    const ref = id ? evidenceById.get(id) : undefined;
    if (!ref) fail(`${label} references missing evidence`);
    else if (ref.kind !== expectedKind) fail(`${label} evidence must have kind ${expectedKind}`);
  };

  const inventory = pack.contract_inventory;
  if (!inventory) fail("contract_inventory is required");
  else {
    requireEvidence(inventory.evidence_id, "contract_inventory", "contract_inventory");
    const required = Array.isArray(inventory.required_contract_ids) ? inventory.required_contract_ids : [];
    const observed = Array.isArray(inventory.observed_contract_ids) ? inventory.observed_contract_ids : [];
    if (!Array.isArray(inventory.required_contract_ids) || !Array.isArray(inventory.observed_contract_ids) || [...required, ...observed].some((id) => !nonEmpty(id))) fail("contract inventory ids must be string arrays");
    if (!required.length || !unique(required) || !unique(observed)) fail("contract inventory ids must be non-empty and unique");
    const missing = required.filter((id) => !observed.includes(id));
    if (missing.length) fail(`required contracts absent from observed inventory: ${missing.join(", ")}`);
  }

  const scenarios = Array.isArray(pack.scenarios) ? pack.scenarios : [];
  if (!scenarios.length) fail("scenario results are required");
  if (!unique(scenarios.map((scenario) => scenario && scenario.id).filter(nonEmpty))) fail("scenario ids must be unique");
  const artifactEvidenceIds = new Set<string>();
  scenarios.forEach((scenario) => {
    if (!scenario || typeof scenario !== "object") { fail("scenario result must be an object"); return; }
    if (!nonEmpty(scenario.id) || scenario.status !== "passed" || !isoDate(scenario.executed_at)) fail(`scenario ${scenario.id || "<unknown>"} is not a timestamped passing result`);
    requireEvidence(scenario.evidence_id, `scenario ${scenario.id}`, "scenario_result");
    const artifactRef = scenario.artifact_evidence_id ? evidenceById.get(scenario.artifact_evidence_id) : undefined;
    if (!artifactRef) fail(`scenario ${scenario.id} references missing raw artifact evidence`);
    else if (artifactRef.kind !== "scenario_artifact") fail(`scenario ${scenario.id} artifact evidence must have kind scenario_artifact`);
    if (scenario.artifact_evidence_id && artifactEvidenceIds.has(scenario.artifact_evidence_id)) fail(`scenario artifact evidence is duplicated: ${scenario.artifact_evidence_id}`);
    if (scenario.artifact_evidence_id) artifactEvidenceIds.add(scenario.artifact_evidence_id);
    if (!/^[0-9a-f]{64}$/i.test(scenario.evidence_sha256 || "")) fail(`scenario ${scenario.id} has no valid server-recorded artifact SHA-256`);
    if (!nonEmpty(scenario.execution_ref)) fail(`scenario ${scenario.id} has no server-recorded execution binding`);
    const scenarioSummaryRef = scenario.evidence_id ? evidenceById.get(scenario.evidence_id) : undefined;
    if (scenarioSummaryRef?.kind === "scenario_result") {
      try {
        const summary = JSON.parse(readFileSync(resolve(dirname(resolve(packPath)), scenarioSummaryRef.path), "utf8")) as Record<string, unknown>;
        const payload = summary.payload && typeof summary.payload === "object" ? summary.payload as Record<string, unknown> : summary;
        const rows = Array.isArray(payload.scenarios) ? payload.scenarios as Array<Record<string, unknown>> : [];
        const durable = rows.find((row) => row.id === scenario.id);
        if (!durable || durable.evidence_sha256 !== scenario.evidence_sha256 || durable.execution_ref !== scenario.execution_ref || durable.status !== scenario.status) {
          fail(`scenario ${scenario.id} does not match its durable staging scenario record`);
        }
      } catch {
        fail(`scenario ${scenario.id} durable staging scenario record is unreadable`);
      }
    }
    if (artifactRef && scenarioRun && scenarioRun.execution_id && scenarioRun.tenant_ref) {
      try {
        const artifactPath = resolve(dirname(resolve(packPath)), artifactRef.path);
        const artifact = JSON.parse(readFileSync(artifactPath, "utf8")) as Record<string, unknown>;
        if (hasSensitiveArtifactValue(artifact)) fail(`scenario ${scenario.id} raw artifact contains unredacted sensitive values`);
        if (artifact.scenario_id !== scenario.id) fail(`scenario ${scenario.id} raw artifact identifies a different scenario`);
        if (artifact.execution_id !== scenarioRun.execution_id) fail(`scenario ${scenario.id} raw artifact execution does not match scenario_run`);
        if (artifact.tenant_ref !== scenarioRun.tenant_ref) fail(`scenario ${scenario.id} raw artifact tenant does not match scenario_run`);
        if (artifact.outcome !== "passed" || artifact.assertions_failed !== 0) fail(`scenario ${scenario.id} raw artifact is not a passing execution`);
        if (artifactRef.sha256.toLowerCase() !== scenario.evidence_sha256.toLowerCase()) fail(`scenario ${scenario.id} server-recorded SHA-256 does not match raw artifact evidence`);
      } catch {
        // Evidence path/hash diagnostics above are retained; malformed artifact is an independent proof failure.
        fail(`scenario ${scenario.id} raw artifact is missing or invalid JSON`);
      }
    }
  });
  const scenarioIds = new Set(scenarios.filter((scenario) => scenario && typeof scenario === "object").map((scenario) => scenario.id));
  REQUIRED_IDENTITY_CONTINUITY_SCENARIOS.forEach((id) => {
    if (!scenarioIds.has(id)) fail(`mandatory scenario result is absent: ${id}`);
  });

  const graphVersions = Array.isArray(pack.graph_versions) ? pack.graph_versions : [];
  if (!graphVersions.length) fail("graph version observations are required");
  graphVersions.forEach((graph) => {
    if (!graph || typeof graph !== "object") { fail("graph version observation must be an object"); return; }
    if (!nonEmpty(graph.tenant_id) || !nonEmpty(graph.graph) || !nonEmpty(graph.before) || !nonEmpty(graph.after) || graph.before === graph.after || !isoDate(graph.observed_at)) fail("graph version observations require tenant, graph, distinct versions, and timestamp");
    requireEvidence(graph.evidence_id, `graph ${graph.graph}`, "graph_versions");
  });

  const jobs = Array.isArray(pack.restatement_jobs) ? pack.restatement_jobs : [];
  if (!jobs.length) fail("restatement job evidence is required");
  jobs.forEach((job) => {
    if (!job || typeof job !== "object") { fail("restatement job must be an object"); return; }
    if (!nonEmpty(job.tenant_id) || !nonEmpty(job.job_id) || job.status !== "succeeded" || !nonEmpty(job.projection) || !nonEmpty(job.source_graph_version) || !nonEmpty(job.resulting_graph_version) || !isoDate(job.completed_at)) fail(`restatement job ${job.job_id || "<unknown>"} is not a complete successful job record`);
    requireEvidence(job.evidence_id, `restatement job ${job.job_id}`, "restatement_job");
    if (graphVersions.length && !graphVersions.some((graph) => graph && graph.tenant_id === job.tenant_id && graph.before === job.source_graph_version && graph.after === job.resulting_graph_version)) fail(`restatement job ${job.job_id} has no matching tenant graph version transition`);
  });

  const projectionOutcomes = Array.isArray(pack.projection_outcomes) ? pack.projection_outcomes : [];
  if (!projectionOutcomes.length) fail("projection outcomes are required");
  const projections = new Map<string, string>();
  projectionOutcomes.forEach((outcome) => {
    if (!outcome || typeof outcome !== "object") { fail("projection outcome must be an object"); return; }
    if (!nonEmpty(outcome.projection) || !["completed", "unsupported", "failed"].includes(outcome.status)) fail("projection outcome requires a projection name and explicit status");
    if (projections.has(outcome.projection)) fail(`projection outcome is duplicated: ${outcome.projection}`);
    projections.set(outcome.projection, outcome.status);
    requireEvidence(outcome.evidence_id, `projection ${outcome.projection}`, "projection_outcome");
  });
  Object.entries(REQUIRED_PROJECTION_OUTCOMES).forEach(([projection, expected]) => {
    if (projections.get(projection) !== expected) fail(`projection ${projection} must be explicitly ${expected}`);
  });

  const flags = pack.feature_flags;
  if (!flags || !flags.values || typeof flags.values !== "object" || Array.isArray(flags.values)) fail("feature_flags values are required");
  else {
    requireEvidence(flags.evidence_id, "feature_flags", "feature_flags");
    const requiredEnabled = Array.isArray(flags.required_enabled) ? flags.required_enabled : [];
    if (!Array.isArray(flags.required_enabled) || requiredEnabled.some((name) => !nonEmpty(name))) fail("feature_flags.required_enabled must be a string array");
    requiredEnabled.forEach((name) => {
      if (flags.values[name] !== true) fail(`required feature flag is absent or disabled: ${name}`);
    });
  }
  const uiEvidence = pack.ui_evidence;
  if (uiEvidence === undefined) fail("authenticated live activation and review_queue UI evidence is required");
  if (uiEvidence !== undefined) {
    if (!Array.isArray(uiEvidence)) fail("ui_evidence must be an array when present");
    else {
      const uiIds = new Set<string>();
      uiEvidence.forEach((item) => {
        if (!item || typeof item !== "object") { fail("ui_evidence item must be an object"); return; }
        if (!nonEmpty(item.id) || uiIds.has(item.id)) fail("UI evidence IDs must be non-empty and unique");
        uiIds.add(item.id);
        if (!nonEmpty(item.test_id) || !nonEmpty(item.tenant_ref) || !isoDate(item.captured_at)) fail(`UI evidence ${item.id || "<unknown>"} needs test, tenant, and capture time`);
        if (!["activation", "review_queue", "profile_360"].includes(item.surface)) fail(`UI evidence ${item.id || "<unknown>"} has an unknown identity surface`);
        const isFixture = item.evidence_class === "ui_fixture_only"
          && item.api_mode === "playwright_route_fixture"
          && item.live_staging_claim === false;
        const isLive = item.evidence_class === "ui_live_staging"
          && item.api_mode === "authenticated_real_backend"
          && item.live_staging_claim === true
          && item.deployment_id === pack.environment?.deployment_id
          && item.tenant_ref === pack.scenario_run?.tenant_ref;
        if (!isFixture && !isLive) fail(`UI evidence ${item.id || "<unknown>"} has invalid fixture or live staging provenance`);
        requireEvidence(item.structured_evidence_id, `UI evidence ${item.id} observations`, "ui_e2e");
        requireEvidence(item.screenshot_evidence_id, `UI evidence ${item.id} screenshot`, "ui_e2e_screenshot");
        const structuredRef = evidenceById.get(item.structured_evidence_id);
        if (structuredRef) {
          try {
            const payload = JSON.parse(readFileSync(resolve(dirname(resolve(packPath)), structuredRef.path), "utf8")) as Record<string, unknown>;
            if (payload.evidence_class !== item.evidence_class || payload.api_mode !== item.api_mode || payload.live_staging_claim !== item.live_staging_claim || payload.test_id !== item.test_id || payload.surface !== item.surface || payload.tenant_ref !== item.tenant_ref) {
              fail(`UI evidence ${item.id} observations do not match its manifest metadata`);
            }
            if (isLive) {
              if (payload.deployment_id !== item.deployment_id) fail(`UI evidence ${item.id} is bound to a different deployment`);
              const pageOrigin = new URL(String(payload.page_origin || ""));
              const apiOrigin = new URL(String(payload.api_origin || ""));
              if (pageOrigin.protocol !== "https:" || apiOrigin.protocol !== "https:") fail(`UI evidence ${item.id} origins must use HTTPS`);
              const requiredRoutes = item.surface === "activation"
                ? ["/v1/me", "/v1/capabilities", "/v1/admin/identity/activation-status"]
                : item.surface === "review_queue"
                  ? ["/v1/me", "/v1/capabilities", "/v1/admin/identity/review-queue"]
                  : [];
              const observations = Array.isArray(payload.api_observations) ? payload.api_observations : [];
              for (const route of requiredRoutes) {
                if (!observations.some((entry: any) => entry?.path === route && Number.isInteger(entry?.status) && entry.status >= 200 && entry.status < 300)) {
                  fail(`UI evidence ${item.id} is missing a successful live response for ${route}`);
                }
              }
              if (requiredRoutes.length === 0) fail(`UI evidence ${item.id} cannot satisfy a live staging surface gate`);
            } else if (payload.live_staging_claim !== false) {
              fail(`UI evidence ${item.id} fixture payload overstates live staging`);
            }
          } catch { fail(`UI evidence ${item.id} structured observations are unreadable`); }
        }
        const screenshotRef = evidenceById.get(item.screenshot_evidence_id);
        if (screenshotRef) {
          try {
            if (!readFileSync(resolve(dirname(resolve(packPath)), screenshotRef.path)).subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
              fail(`UI evidence ${item.id} screenshot is not a PNG`);
            }
          } catch { fail(`UI evidence ${item.id} screenshot is unreadable`); }
        }
      });
      const liveSurfaces = new Set(uiEvidence
        .filter((item) => item?.evidence_class === "ui_live_staging" && item?.live_staging_claim === true)
        .map((item) => item?.surface));
      if (!liveSurfaces.has("activation") || !liveSurfaces.has("review_queue")) fail("live staging UI evidence must include activation and review_queue surfaces");
    }
  }
  return { valid: errors.length === 0, errors };
}

/** Validate and write a canonical JSON artifact; invalid evidence is never emitted as a pack. */
export function buildIdentityContinuityPack(inputPath: string, outputPath: string): PackValidation {
  let value: unknown;
  try { value = JSON.parse(readFileSync(inputPath, "utf8")); }
  catch (error) { return { valid: false, errors: [`cannot read evidence manifest: ${String(error)}`] }; }
  const validation = validateIdentityContinuityPack(value, inputPath);
  if (!validation.valid) return validation;
  const pack = value as IdentityContinuityPack;
  const outputDirectory = dirname(resolve(outputPath));
  try {
    mkdirSync(outputDirectory, { recursive: true });
    const realOutputDirectory = realpathSync(outputDirectory);
    const evidenceDirectory = resolve(realOutputDirectory, "evidence");
    mkdirSync(evidenceDirectory, { recursive: true });
    const realEvidenceDirectory = realpathSync(evidenceDirectory);
    if (!realEvidenceDirectory.startsWith(`${realOutputDirectory}${sep}`)) {
      return { valid: false, errors: ["output evidence directory resolves outside the selected output directory"] };
    }

    const copied: string[] = [];
    try {
      const inputDirectory = realpathSync(dirname(resolve(inputPath)));
      const copiedEvidence = pack.evidence.map((reference, index) => {
        const inputEvidencePath = resolve(inputDirectory, reference.path);
        const realInputEvidencePath = realpathSync(inputEvidencePath);
        if (isAbsolute(reference.path) || !realInputEvidencePath.startsWith(`${inputDirectory}${sep}`)) {
          throw new Error(`evidence ${reference.id} resolves outside the manifest directory`);
        }
        const outputRelative = `evidence/${index}-${reference.sha256.toLowerCase()}.json`;
        const destination = resolve(realOutputDirectory, outputRelative);
        copyFileSync(realInputEvidencePath, destination, 1);
        copied.push(destination);
        return { ...reference, path: outputRelative };
      });
      const normalized = { ...pack, evidence: copiedEvidence };
      const outputValidation = validateIdentityContinuityPack(normalized, resolve(outputPath));
      if (!outputValidation.valid) throw new Error(outputValidation.errors.join("; "));
      writeFileSync(outputPath, `${JSON.stringify(normalized, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
      return { valid: true, errors: [] };
    } catch (error) {
      copied.forEach((path) => rmSync(path, { force: true }));
      const message = error && typeof error === "object" && "code" in error && error.code === "EEXIST"
        ? "proof pack or evidence output already exists; choose a fresh output directory"
        : `cannot build proof pack: ${String(error)}`;
      return { valid: false, errors: [message] };
    }
  } catch (error) {
    return { valid: false, errors: [`cannot prepare proof pack output: ${String(error)}`] };
  }
}
