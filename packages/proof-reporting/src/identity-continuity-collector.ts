import { createHash } from "crypto";
import { existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from "fs";
import { dirname, isAbsolute, join, resolve, sep } from "path";
import { REQUIRED_IDENTITY_CONTINUITY_SCENARIOS, REQUIRED_PROJECTION_OUTCOMES, validateIdentityContinuityPack, type EvidenceReference, type IdentityContinuityPack } from "./identity-continuity-pack";

type CaptureEvidence = { id: string; kind: Exclude<EvidenceReference["kind"], "scenario_artifact" | "ui_e2e" | "ui_e2e_screenshot">; path: string };
type CaptureScenarioArtifact = { scenario_id: string; path: string };
type CaptureUiFixtureEvidence = {
  id: string; surface: "activation" | "review_queue" | "profile_360"; test_id: string; tenant_ref: string;
  evidence_class: "ui_fixture_only"; api_mode: "playwright_route_fixture"; live_staging_claim: false;
  captured_at: string; structured_path: string; structured_sha256: string; screenshot_path: string; screenshot_sha256: string;
};
type CaptureUiLiveEvidence = {
  id: string; surface: "activation" | "review_queue"; test_id: string; tenant_ref: string; deployment_id: string;
  evidence_class: "ui_live_staging"; api_mode: "authenticated_real_backend"; live_staging_claim: true;
  captured_at: string; structured_path: string; structured_sha256: string; screenshot_path: string; screenshot_sha256: string;
};
type CaptureUiEvidence = CaptureUiFixtureEvidence | CaptureUiLiveEvidence;
export type IdentityContinuityCapture = Omit<IdentityContinuityPack, "evidence"> & {
  evidence_sources: CaptureEvidence[];
  scenario_artifacts: CaptureScenarioArtifact[];
  ui_evidence: CaptureUiEvidence[];
  scenarios: Array<Omit<IdentityContinuityPack["scenarios"][number], "artifact_evidence_id"> & { artifact_evidence_id?: string }>;
};
export type CollectionResult = { collected: boolean; packPath?: string; errors: string[] };

const SENSITIVE_KEY = /(?:email|phone|mobile|address|(?:customer|person|buyer|first|last|full)_?name|token|secret|password|authorization|cookie|credential|api.?key|access.?key|refresh.?token|ip.?address|birth.?date|payment|card.?number)/i;
const SENSITIVE_VALUE = /(?:bearer\s+\S+|(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]+|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/i;
const EVIDENCE_KINDS: CaptureEvidence["kind"][] = ["contract_inventory", "scenario_result", "graph_versions", "restatement_job", "projection_outcome", "feature_flags"];
const MAX_CAPTURE_BYTES = 5 * 1024 * 1024;
const MAX_EVIDENCE_SOURCE_BYTES = 2 * 1024 * 1024;
const MAX_EVIDENCE_SOURCES = 32;
const MAX_UI_SCREENSHOT_BYTES = 5 * 1024 * 1024;
const MAX_UI_STRUCTURED_BYTES = 512 * 1024;

function redact(value: unknown, key = ""): unknown {
  if (SENSITIVE_KEY.test(key)) return "[REDACTED]";
  if (typeof value === "string") {
    const digits = value.replace(/\D/g, "").length;
    const looksLikePhone = /^[+\d().\s/-]+$/.test(value) && digits >= 10 && digits <= 15;
    return SENSITIVE_VALUE.test(value) || looksLikePhone ? "[REDACTED]" : value;
  }
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([childKey, child]) => [childKey, redact(child, childKey)]));
  }
  return value;
}

function containsSensitiveValue(value: unknown): boolean {
  if (typeof value === "string") {
    const digits = value.replace(/\D/g, "").length;
    const looksLikePhone = /^[+\d().\s/-]+$/.test(value) && digits >= 10 && digits <= 15;
    return SENSITIVE_VALUE.test(value) || looksLikePhone;
  }
  if (Array.isArray(value)) return value.some(containsSensitiveValue);
  if (value && typeof value === "object") return Object.values(value as Record<string, unknown>).some(containsSensitiveValue);
  return false;
}

function safeSourcePath(capturePath: string, sourcePath: string): string {
  if (isAbsolute(sourcePath)) throw new Error(`evidence source path must be relative: ${sourcePath}`);
  const captureRoot = realpathSync(dirname(resolve(capturePath)));
  const candidate = resolve(captureRoot, sourcePath);
  if (!candidate.startsWith(`${captureRoot}${sep}`)) throw new Error(`evidence source path escapes capture directory: ${sourcePath}`);
  if (!existsSync(candidate)) throw new Error(`evidence source is missing: ${sourcePath}`);
  const actual = realpathSync(candidate);
  if (!actual.startsWith(`${captureRoot}${sep}`)) throw new Error(`evidence source resolves outside capture directory: ${sourcePath}`);
  return actual;
}

/**
 * Collects only explicitly exported staging evidence. This function has no API credentials,
 * fixture fallback, or implicit staging access; absent/unsafe sources fail closed.
 */
export function collectIdentityContinuityEvidence(capturePath: string, outputDirectory: string): CollectionResult {
  const errors: string[] = [];
  let capture: IdentityContinuityCapture;
  try {
    if (statSync(capturePath).size > MAX_CAPTURE_BYTES) throw new Error("capture manifest exceeds 5 MiB limit");
    capture = JSON.parse(readFileSync(capturePath, "utf8")) as IdentityContinuityCapture;
  }
  catch (error) { return { collected: false, errors: [`cannot read capture manifest: ${String(error)}`] }; }
  if (!capture || typeof capture !== "object" || Array.isArray(capture)) {
    return { collected: false, errors: ["capture manifest must be a JSON object"] };
  }
  mkdirSync(outputDirectory, { recursive: true });
  const outputRoot = realpathSync(resolve(outputDirectory));
  const evidenceDir = join(outputRoot, "evidence");
  mkdirSync(evidenceDir, { recursive: true });
  const realEvidenceDir = realpathSync(evidenceDir);
  if (!realEvidenceDir.startsWith(`${outputRoot}${sep}`)) {
    return { collected: false, errors: ["output evidence directory resolves outside the selected output directory"] };
  }
  const evidence: EvidenceReference[] = [];
  const seen = new Set<string>();
  const sources = Array.isArray(capture.evidence_sources) ? capture.evidence_sources : [];
  if (sources.length > MAX_EVIDENCE_SOURCES) errors.push(`capture contains more than ${MAX_EVIDENCE_SOURCES} evidence sources`);
  for (const source of sources.slice(0, MAX_EVIDENCE_SOURCES)) {
    if (!source || typeof source.id !== "string" || !source.id.trim() || !/^[a-zA-Z0-9._-]+$/.test(source.id) || seen.has(source.id)) {
      errors.push(`evidence source has an invalid or duplicate id: ${String(source?.id ?? "<missing>")}`);
      continue;
    }
    seen.add(source.id);
    if (!EVIDENCE_KINDS.includes(source.kind)) {
      errors.push(`evidence source ${source.id} has an unsupported evidence kind`);
      continue;
    }
    if (typeof source.path !== "string" || !source.path.trim()) {
      errors.push(`evidence source ${source.id} has no relative path`);
      continue;
    }
    try {
      const sourcePath = safeSourcePath(capturePath, source.path);
      if (statSync(sourcePath).size > MAX_EVIDENCE_SOURCE_BYTES) throw new Error(`evidence source exceeds 2 MiB limit: ${source.id}`);
      const rawBytes = readFileSync(sourcePath);
      let parsed: unknown;
      try { parsed = JSON.parse(rawBytes.toString("utf8")); }
      catch { throw new Error(`evidence source must be JSON: ${source.path}`); }
      const safeBytes = `${JSON.stringify({
        collector: { source_id: source.id, source_sha256: createHash("sha256").update(rawBytes).digest("hex"), redacted: true },
        payload: redact(parsed),
      }, null, 2)}\n`;
      const outputRelative = `evidence/${source.id}.json`;
      const outputPath = join(outputRoot, outputRelative);
      writeFileSync(outputPath, safeBytes, { encoding: "utf8", flag: "wx" });
      evidence.push({ id: source.id, kind: source.kind, path: outputRelative, sha256: createHash("sha256").update(safeBytes).digest("hex") });
    } catch (error) { errors.push(String(error instanceof Error ? error.message : error)); }
  }

  const scenarioArtifacts = Array.isArray(capture.scenario_artifacts) ? capture.scenario_artifacts : [];
  const artifactScenarioIds = new Set<string>();
  const artifactDigests = new Set<string>();
  const scenarioEvidenceSource = sources.find((source) => source?.kind === "scenario_result");
  let scenarioEvidencePayload: Record<string, unknown> | undefined;
  if (scenarioEvidenceSource) {
    try {
      const sourcePath = safeSourcePath(capturePath, scenarioEvidenceSource.path);
      scenarioEvidencePayload = JSON.parse(readFileSync(sourcePath, "utf8")) as Record<string, unknown>;
    } catch { /* the regular source validation reports the underlying error */ }
  }
  const sourceScenarioRows = Array.isArray(scenarioEvidencePayload?.scenarios) ? scenarioEvidencePayload.scenarios : [];
  for (const item of scenarioArtifacts) {
    if (!item || typeof item.scenario_id !== "string" || !item.scenario_id.trim() || artifactScenarioIds.has(item.scenario_id)) {
      errors.push(`scenario artifact has an invalid or duplicate scenario id: ${String(item?.scenario_id ?? "<missing>")}`);
      continue;
    }
    artifactScenarioIds.add(item.scenario_id);
    const scenario = Array.isArray(capture.scenarios) ? capture.scenarios.find((entry) => entry?.id === item.scenario_id) : undefined;
    const sourceScenario = sourceScenarioRows.find((entry) => entry?.id === item.scenario_id) as Record<string, unknown> | undefined;
    if (!scenario || !sourceScenario || scenario.evidence_sha256 !== sourceScenario.evidence_sha256 || scenario.execution_ref !== sourceScenario.execution_ref) {
      errors.push(`scenario ${item.scenario_id} is not bound to the durable staging capture record`);
      continue;
    }
    if (!/^[0-9a-f]{64}$/i.test(scenario.evidence_sha256 || "")) {
      errors.push(`scenario ${item.scenario_id} has no valid server-recorded artifact SHA-256`);
      continue;
    }
    if (typeof item.path !== "string" || !item.path.trim()) {
      errors.push(`scenario ${item.scenario_id} has no relative raw artifact path`);
      continue;
    }
    try {
      const sourcePath = safeSourcePath(capturePath, item.path);
      const rawBytes = readFileSync(sourcePath);
      if (rawBytes.length > MAX_EVIDENCE_SOURCE_BYTES) throw new Error(`scenario artifact exceeds 2 MiB limit: ${item.scenario_id}`);
      const digest = createHash("sha256").update(rawBytes).digest("hex");
      if (digest.toLowerCase() !== scenario.evidence_sha256.toLowerCase()) throw new Error(`scenario ${item.scenario_id} exact-byte SHA-256 does not match the durable staging capture`);
      if (artifactDigests.has(digest)) throw new Error(`scenario artifact digest is duplicated: ${item.scenario_id}`);
      artifactDigests.add(digest);
      const artifact = JSON.parse(rawBytes.toString("utf8")) as Record<string, unknown>;
      if (containsSensitiveValue(artifact)) throw new Error(`scenario ${item.scenario_id} raw artifact contains unredacted sensitive values`);
      if (artifact.scenario_id !== item.scenario_id) throw new Error(`scenario ${item.scenario_id} raw artifact identifies a different scenario`);
      if (artifact.execution_id !== capture.scenario_run?.execution_id) throw new Error(`scenario ${item.scenario_id} raw artifact execution does not match the bound run`);
      if (artifact.tenant_ref !== capture.scenario_run?.tenant_ref) throw new Error(`scenario ${item.scenario_id} raw artifact tenant does not match the bound run`);
      if (capture.scenario_run?.deployment_id !== capture.environment?.deployment_id) throw new Error("scenario run deployment does not match the staging capture deployment");
      if (artifact.outcome !== "passed" || artifact.assertions_failed !== 0) throw new Error(`scenario ${item.scenario_id} raw artifact is not a passing execution`);
      const artifactId = `scenario-artifact-${item.scenario_id}`;
      const outputRelative = `evidence/${artifactId}.json`;
      writeFileSync(join(outputRoot, outputRelative), rawBytes, { flag: "wx" });
      evidence.push({ id: artifactId, kind: "scenario_artifact", path: outputRelative, sha256: digest });
      scenario.artifact_evidence_id = artifactId;
    } catch (error) { errors.push(String(error instanceof Error ? error.message : error)); }
  }

  const uiEvidence = Array.isArray(capture.ui_evidence) ? capture.ui_evidence : [];
  const uiIds = new Set<string>();
  const copiedUiEvidence: NonNullable<IdentityContinuityPack["ui_evidence"]> = [];
  const liveSurfaces = new Set<string>();
  for (const item of uiEvidence) {
    if (!item || typeof item.id !== "string" || !/^(?:[0-9a-f]{20}|[0-9a-f]{24})$/.test(item.id) || uiIds.has(item.id)) {
      errors.push(`UI evidence has an invalid or duplicate id: ${String(item?.id ?? "<missing>")}`);
      continue;
    }
    uiIds.add(item.id);
    const isLive = item.evidence_class === "ui_live_staging";
    if (isLive) {
      if (item.api_mode !== "authenticated_real_backend" || item.live_staging_claim !== true || item.deployment_id !== capture.environment?.deployment_id || item.tenant_ref !== capture.scenario_run?.tenant_ref) {
        errors.push(`UI evidence ${item.id} is not bound to this authenticated staging tenant and deployment`);
        continue;
      }
      if (!(item.surface === "activation" || item.surface === "review_queue") || !item.test_id?.trim() || !/^tenant:[0-9a-f]{32,64}$/.test(item.tenant_ref) || !/^\d{4}-\d\d-\d\dT/.test(item.captured_at)) {
        errors.push(`UI evidence ${item.id} has invalid live surface, test, tenant reference, or timestamp`);
        continue;
      }
      liveSurfaces.add(item.surface);
    } else {
      if (item.evidence_class !== "ui_fixture_only" || item.api_mode !== "playwright_route_fixture" || item.live_staging_claim !== false) {
        errors.push(`UI evidence ${String((item as { id?: string }).id ?? "<unknown>")} must be explicitly fixture-only or authenticated live staging`);
        continue;
      }
      if (!/^(activation|review_queue|profile_360)$/.test(item.surface) || !item.test_id?.trim() || !/^tenant_identity_e2e_[A-Za-z0-9_-]+$/.test(item.tenant_ref) || !/^\d{4}-\d\d-\d\dT/.test(item.captured_at)) {
        errors.push(`UI evidence ${item.id} has invalid fixture surface, test, synthetic tenant, or timestamp`);
        continue;
      }
    }
    const sources = [
      { role: "observations", path: item.structured_path, digest: item.structured_sha256, kind: "ui_e2e" as const, extension: ".json" },
      { role: "screenshot", path: item.screenshot_path, digest: item.screenshot_sha256, kind: "ui_e2e_screenshot" as const, extension: ".png" },
    ];
    const refs: Record<string, string> = {};
    for (const source of sources) {
      try {
        if (!/^[0-9a-f]{64}$/.test(source.digest)) throw new Error(`UI ${source.role} has invalid SHA-256`);
        const sourcePath = safeSourcePath(capturePath, source.path);
        const bytes = readFileSync(sourcePath);
        const limit = source.role === "screenshot" ? MAX_UI_SCREENSHOT_BYTES : MAX_UI_STRUCTURED_BYTES;
        if (bytes.length > limit) throw new Error(`UI ${source.role} exceeds size limit`);
        if (createHash("sha256").update(bytes).digest("hex") !== source.digest) throw new Error(`UI ${source.role} exact-byte SHA-256 mismatch`);
        const evidenceId = `ui-${item.id}-${source.role}`;
        const outputRelative = `evidence/${evidenceId}${source.extension}`;
        if (source.role === "observations") {
          const data = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
          if (containsSensitiveValue(data)) throw new Error("UI observations contain unredacted sensitive values");
          if (isLive) {
            const parsed = new URL(String(data.api_origin ?? ""));
            const pageOrigin = new URL(String(data.page_origin ?? ""));
            const expectedRoutes = item.surface === "activation"
              ? new Set(["/v1/me", "/v1/capabilities", "/v1/admin/identity/activation-status"])
              : new Set(["/v1/me", "/v1/capabilities", "/v1/admin/identity/review-queue"]);
            const observations = Array.isArray(data.api_observations) ? data.api_observations as Array<Record<string, unknown>> : [];
            const successfulRoutes = new Set(observations.filter((row) => Number.isInteger(row.status) && Number(row.status) >= 200 && Number(row.status) < 300).map((row) => row.path));
            if (data.schema_version !== "aether.identity-ui-evidence.v2" || data.evidence_class !== "ui_live_staging" || data.api_mode !== "authenticated_real_backend" || data.live_staging_claim !== true || data.deployment_id !== item.deployment_id || data.test_id !== item.test_id || data.surface !== item.surface || data.tenant_ref !== item.tenant_ref || parsed.protocol !== "https:" || pageOrigin.protocol !== "https:" || ![...expectedRoutes].every((route) => successfulRoutes.has(route))) {
              throw new Error("structured UI evidence does not prove authenticated staging UI/API responses for this deployment");
            }
          } else if (data.schema_version !== "aether.identity-ui-evidence.v1" || data.evidence_class !== "ui_fixture_only" || data.api_mode !== "playwright_route_fixture" || data.live_staging_claim !== false || data.test_id !== item.test_id || data.surface !== item.surface || data.tenant_ref !== item.tenant_ref) {
            throw new Error("structured UI evidence does not match fixture-only capture metadata");
          }
        } else if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
          throw new Error("UI screenshot is not a PNG");
        }
        writeFileSync(join(outputRoot, outputRelative), bytes, { flag: "wx" });
        evidence.push({ id: evidenceId, kind: source.kind, path: outputRelative, sha256: source.digest });
        refs[source.role] = evidenceId;
      } catch (error) { errors.push(`UI evidence ${item.id}: ${String(error instanceof Error ? error.message : error)}`); }
    }
    if (refs.observations && refs.screenshot) {
      copiedUiEvidence.push({
        id: item.id, surface: item.surface, test_id: item.test_id, tenant_ref: item.tenant_ref,
        ...(isLive ? { deployment_id: item.deployment_id } : {}),
        evidence_class: isLive ? "ui_live_staging" : "ui_fixture_only",
        api_mode: isLive ? "authenticated_real_backend" : "playwright_route_fixture",
        live_staging_claim: isLive,
        captured_at: item.captured_at, structured_evidence_id: refs.observations, screenshot_evidence_id: refs.screenshot,
      });
    }
  }

  if (!liveSurfaces.has("activation") || !liveSurfaces.has("review_queue")) {
    errors.push("live staging UI evidence must include authenticated activation and review_queue surfaces; fixture evidence cannot satisfy this requirement");
  }

  const scenarios = Array.isArray(capture.scenarios) ? capture.scenarios : [];
  const missingScenarioIds = REQUIRED_IDENTITY_CONTINUITY_SCENARIOS.filter((id) => !scenarios.some((scenario) => scenario?.id === id && scenario.status === "passed"));
  missingScenarioIds.forEach((id) => errors.push(`missing passing staging scenario evidence: ${id}`));
  const missingEvidenceKinds = EVIDENCE_KINDS;
  missingEvidenceKinds.filter((kind) => !evidence.some((ref) => ref.kind === kind)).forEach((kind) => errors.push(`missing captured staging evidence kind: ${kind}`));
  for (const [projection, expected] of Object.entries(REQUIRED_PROJECTION_OUTCOMES)) {
    const actual = capture.projection_outcomes?.find((outcome) => outcome.projection === projection)?.status;
    if (actual !== expected) errors.push(`projection ${projection} is ${actual ?? "missing"}; required captured status is ${expected}`);
  }

  const normalized = { ...capture } as Record<string, unknown>;
  delete normalized.evidence_sources;
  if (uiEvidence.length) normalized.ui_evidence = copiedUiEvidence;
  normalized.evidence = evidence;
  const sanitizedPack = redact(normalized) as Record<string, unknown>;
  const packPath = join(outputRoot, "identity-continuity-pack.json");
  if (!errors.length) {
    const validation = validateIdentityContinuityPack(sanitizedPack, packPath);
    errors.push(...validation.errors);
  }
  if (errors.length) {
    const report = { schema_version: "1.0.0", status: "incomplete", captured_at: capture.generated_at ?? null, missing_or_invalid: [...new Set(errors)].sort(), evidence_collected: evidence.map(({ id, kind, path, sha256 }) => ({ id, kind, path, sha256 })) };
    try { writeFileSync(join(outputRoot, "collection-report.json"), `${JSON.stringify(report, null, 2)}\n`); }
    catch (error) { return { collected: false, errors: [...report.missing_or_invalid, `cannot write collection report: ${String(error)}`] }; }
    return { collected: false, errors: report.missing_or_invalid };
  }
  try { writeFileSync(packPath, `${JSON.stringify(sanitizedPack, null, 2)}\n`, { encoding: "utf8", flag: "wx" }); }
  catch (error) {
    const message = error && typeof error === "object" && "code" in error && error.code === "EEXIST"
      ? "proof pack output already exists; choose a fresh output directory"
      : `cannot write proof pack: ${String(error)}`;
    return { collected: false, errors: [message] };
  }
  return { collected: true, packPath, errors: [] };
}
