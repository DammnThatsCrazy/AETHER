import { createHash } from "crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync, existsSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it } from "vitest";
import { collectIdentityContinuityEvidence } from "./identity-continuity-collector";
import { REQUIRED_IDENTITY_CONTINUITY_SCENARIOS, REQUIRED_PROJECTION_OUTCOMES, validateIdentityContinuityPack } from "./identity-continuity-pack";

const roots: string[] = [];
function captureFixture() {
  const root = mkdtempSync(join(tmpdir(), "aether-staging-capture-"));
  roots.push(root);
  mkdirSync(join(root, "source"));
  const evidence_sources = [
    ["contracts", "contract_inventory"], ["scenario-evidence", "scenario_result"], ["graph", "graph_versions"],
    ["jobs", "restatement_job"], ["projections", "projection_outcome"], ["flags", "feature_flags"],
  ].map(([id, kind]) => {
    writeFileSync(join(root, "source", `${id}.json`), JSON.stringify({ captured_at: "2026-09-27T18:00:00Z", evidence: id, contact: { email: "person@example.test", phone: "+1 202-555-0199" }, headers: { Authorization: "Bearer secret-value" } }));
    return { id, kind, path: `source/${id}.json` };
  });
  const scenarioRun = { execution_id: "execution-42", tenant_ref: `tenant:${"c".repeat(32)}`, deployment_id: "staging-deploy-42" };
  const scenarios = REQUIRED_IDENTITY_CONTINUITY_SCENARIOS.map((id, index) => {
    const artifact = { schema_version: "1.0.0", scenario_id: id, execution_id: scenarioRun.execution_id, tenant_ref: scenarioRun.tenant_ref,
      started_at: "2026-09-27T17:49:00Z", executed_at: "2026-09-27T17:50:00Z", outcome: "passed", assertions_passed: 2, assertions_failed: 0, failure: null, api_trace: [] };
    const bytes = `${JSON.stringify(artifact)}\n`;
    const path = `source/scenarios/${id}.json`;
    mkdirSync(join(root, "source", "scenarios"), { recursive: true });
    writeFileSync(join(root, path), bytes);
    return { id, status: "passed", evidence_id: "scenario-evidence", executed_at: "2026-09-27T17:50:00Z",
      evidence_sha256: createHash("sha256").update(bytes).digest("hex"), execution_ref: `execution-hash-${index}` };
  });
  const scenarioEvidenceSource = evidence_sources.find((source) => source.kind === "scenario_result")!;
  writeFileSync(join(root, scenarioEvidenceSource.path), JSON.stringify({ scenarios }));
  const capture: any = {
    schema_version: "1.0.0",
    proof_id: "staging-proof-42",
    generated_at: "2026-09-27T18:00:00Z",
    commit: { sha: "a".repeat(40), branch: "identity-continuity" },
    environment: { name: "staging", deployment_id: "staging-deploy-42", observed_at: "2026-09-27T17:59:00Z" },
    scenario_run: scenarioRun,
    scenario_artifacts: scenarios.map((scenario) => ({ scenario_id: scenario.id, path: `source/scenarios/${scenario.id}.json` })),
    evidence_sources,
    contract_inventory: { evidence_id: "contracts", required_contract_ids: ["identity-claim", "source-identity"], observed_contract_ids: ["identity-claim", "source-identity"] },
    scenarios,
    graph_versions: [{ tenant_id: "tenant-hash-1", graph: "identity", before: "v1", after: "v2", observed_at: "2026-09-27T17:52:00Z", evidence_id: "graph" }],
    restatement_jobs: [{ tenant_id: "tenant-hash-1", job_id: "restatement-1", status: "succeeded", projection: "profile_360", source_graph_version: "v1", resulting_graph_version: "v2", completed_at: "2026-09-27T17:55:00Z", evidence_id: "jobs" }],
    projection_outcomes: Object.entries(REQUIRED_PROJECTION_OUTCOMES).map(([projection, status]) => ({ projection, status, evidence_id: "projections" })),
    feature_flags: { evidence_id: "flags", values: { IDENTITY_CONTINUITY: true }, required_enabled: ["IDENTITY_CONTINUITY"] },
  };
  const uiRoot = join(root, "source", "ui-live");
  mkdirSync(uiRoot, { recursive: true });
  const screenshot = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]);
  capture.ui_evidence = (["activation", "review_queue"] as const).map((surface) => {
    const id = surface === "activation" ? "1".repeat(24) : "2".repeat(24);
    const testId = `live ${surface} renders against staging`;
    const routes = surface === "activation"
      ? ["/v1/me", "/v1/capabilities", "/v1/admin/identity/activation-status"]
      : ["/v1/me", "/v1/capabilities", "/v1/admin/identity/review-queue"];
    const observations = {
      schema_version: "aether.identity-ui-evidence.v2", evidence_class: "ui_live_staging",
      api_mode: "authenticated_real_backend", live_staging_claim: true,
      test_id: testId, surface, tenant_ref: scenarioRun.tenant_ref, deployment_id: scenarioRun.deployment_id,
      captured_at: "2026-09-27T18:00:00Z", page_origin: "https://app.staging.example",
      api_origin: "https://api.staging.example", page_path: surface === "activation" ? "/identity/activation" : "/identity/reviews",
      visible_headings: [surface], api_observations: routes.map((path) => ({ method: "GET", path, status: 200 })),
      artifacts: { screenshot: `${id}-screenshot.png`, structured: `${id}-observations.json` },
    };
    const structured = Buffer.from(`${JSON.stringify(observations, null, 2)}\n`);
    const screenshotPath = `source/ui-live/${id}-screenshot.png`;
    const structuredPath = `source/ui-live/${id}-observations.json`;
    writeFileSync(join(root, screenshotPath), screenshot);
    writeFileSync(join(root, structuredPath), structured);
    return {
      id, surface, test_id: testId, tenant_ref: scenarioRun.tenant_ref, deployment_id: scenarioRun.deployment_id,
      evidence_class: "ui_live_staging", api_mode: "authenticated_real_backend", live_staging_claim: true,
      captured_at: observations.captured_at, structured_path: structuredPath,
      structured_sha256: createHash("sha256").update(structured).digest("hex"),
      screenshot_path: screenshotPath, screenshot_sha256: createHash("sha256").update(screenshot).digest("hex"),
    };
  });
  const capturePath = join(root, "capture.json");
  writeFileSync(capturePath, JSON.stringify(capture));
  return { root, capturePath, capture };
}

afterEach(() => roots.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true })));

describe("identity continuity staging evidence collector", () => {
  it("collects real exported evidence deterministically and redacts sensitive source data", () => {
    const { root, capturePath } = captureFixture();
    const first = join(root, "out-a");
    const second = join(root, "out-b");
    const collectedA = collectIdentityContinuityEvidence(capturePath, first);
    const collectedB = collectIdentityContinuityEvidence(capturePath, second);
    expect(collectedA.errors, JSON.stringify(collectedA.errors)).toEqual([]);
    expect(collectedB.collected).toBe(true);
    const packA = readFileSync(join(first, "identity-continuity-pack.json"), "utf8");
    const packB = readFileSync(join(second, "identity-continuity-pack.json"), "utf8");
    expect(packA).toBe(packB);
    expect(validateIdentityContinuityPack(JSON.parse(packA), join(first, "identity-continuity-pack.json")).valid).toBe(true);
    const evidence = readFileSync(join(first, "evidence", "contracts.json"), "utf8");
    expect(evidence).not.toContain("person@example.test");
    expect(evidence).not.toContain("202-555-0199");
    expect(evidence).not.toContain("secret-value");
    expect(evidence).toContain("[REDACTED]");
    expect(evidence).toContain("2026-09-27T18:00:00Z");
  });

  it("binds UI screenshots and observations as fixture-only supplemental pack evidence", () => {
    const { root, capturePath, capture } = captureFixture();
    mkdirSync(join(root, "source", "ui"), { recursive: true });
    const screenshot = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]);
    const observations = {
      schema_version: "aether.identity-ui-evidence.v1", evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: false,
      test_id: "activation renders fixture state", surface: "activation",
      tenant_ref: "tenant_identity_e2e_a", captured_at: "2026-09-27T18:00:00Z",
    };
    const structuredBytes = Buffer.from(`${JSON.stringify(observations, null, 2)}\n`);
    writeFileSync(join(root, "source", "ui", "screenshot.png"), screenshot);
    writeFileSync(join(root, "source", "ui", "observations.json"), structuredBytes);
    capture.ui_evidence.push({
      id: "1234567890abcdef1234", surface: "activation", test_id: observations.test_id,
      tenant_ref: observations.tenant_ref, evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: false,
      captured_at: observations.captured_at,
      structured_path: "source/ui/observations.json", structured_sha256: createHash("sha256").update(structuredBytes).digest("hex"),
      screenshot_path: "source/ui/screenshot.png", screenshot_sha256: createHash("sha256").update(screenshot).digest("hex"),
    });
    writeFileSync(capturePath, JSON.stringify(capture));

    const output = join(root, "ui-output");
    const result = collectIdentityContinuityEvidence(capturePath, output);
    expect(result.errors, result.errors.join("\n")).toEqual([]);
    const pack = JSON.parse(readFileSync(join(output, "identity-continuity-pack.json"), "utf8"));
    expect(pack.ui_evidence).toHaveLength(3);
    expect(pack.ui_evidence.filter((item: { evidence_class: string }) => item.evidence_class === "ui_live_staging")).toHaveLength(2);
    expect(pack.ui_evidence.find((item: { evidence_class: string }) => item.evidence_class === "ui_fixture_only")).toMatchObject({
      surface: "activation", evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: false,
      tenant_ref: "tenant_identity_e2e_a",
    });
    const screenshotRef = pack.evidence.find((item: { kind: string }) => item.kind === "ui_e2e_screenshot");
    expect(readFileSync(join(output, screenshotRef.path))).toEqual(screenshot);
    expect(validateIdentityContinuityPack(pack, join(output, "identity-continuity-pack.json")).valid).toBe(true);
  });

  it("requires both authenticated live staging surfaces even when fixture screenshots are present", () => {
    const { root, capturePath, capture } = captureFixture();
    capture.ui_evidence = capture.ui_evidence.filter((item: { evidence_class: string }) => item.evidence_class === "ui_fixture_only");
    writeFileSync(capturePath, JSON.stringify(capture));
    const result = collectIdentityContinuityEvidence(capturePath, join(root, "fixture-only-ui"));
    expect(result.collected).toBe(false);
    expect(result.errors.join("\n")).toContain("live staging UI evidence must include authenticated activation and review_queue surfaces");
  });

  it("rejects live UI evidence with a different tenant/deployment or unsuccessful identity API responses", () => {
    const { root, capturePath, capture } = captureFixture();
    const wrongBinding = structuredClone(capture);
    wrongBinding.ui_evidence[0].deployment_id = "different-deployment";
    writeFileSync(capturePath, JSON.stringify(wrongBinding));
    const wrongBindingResult = collectIdentityContinuityEvidence(capturePath, join(root, "wrong-live-binding"));
    expect(wrongBindingResult.errors.join("\n")).toContain("not bound to this authenticated staging tenant and deployment");

    const wrongResponse = structuredClone(capture);
    const ui = wrongResponse.ui_evidence[0];
    const observationsPath = join(root, ui.structured_path);
    const observations = JSON.parse(readFileSync(observationsPath, "utf8"));
    observations.api_observations[2].status = 503;
    const bytes = Buffer.from(`${JSON.stringify(observations, null, 2)}\n`);
    writeFileSync(observationsPath, bytes);
    ui.structured_sha256 = createHash("sha256").update(bytes).digest("hex");
    writeFileSync(capturePath, JSON.stringify(wrongResponse));
    const wrongResponseResult = collectIdentityContinuityEvidence(capturePath, join(root, "wrong-live-response"));
    expect(wrongResponseResult.errors.join("\n")).toContain("does not prove authenticated staging UI/API responses");
  });

  it("rejects UI artifacts whose structured record claims live staging", () => {
    const { root, capturePath, capture } = captureFixture();
    mkdirSync(join(root, "source", "ui"), { recursive: true });
    const screenshot = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
    const observations = {
      schema_version: "aether.identity-ui-evidence.v1", evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: true,
      test_id: "activation", surface: "activation", tenant_ref: "tenant_identity_e2e_a",
    };
    const structuredBytes = Buffer.from(JSON.stringify(observations));
    writeFileSync(join(root, "source", "ui", "screenshot.png"), screenshot);
    writeFileSync(join(root, "source", "ui", "observations.json"), structuredBytes);
    capture.ui_evidence = [{
      id: "1234567890abcdef1234", surface: "activation", test_id: "activation",
      tenant_ref: "tenant_identity_e2e_a", evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: false, captured_at: "2026-09-27T18:00:00Z",
      structured_path: "source/ui/observations.json", structured_sha256: createHash("sha256").update(structuredBytes).digest("hex"),
      screenshot_path: "source/ui/screenshot.png", screenshot_sha256: createHash("sha256").update(screenshot).digest("hex"),
    }];
    writeFileSync(capturePath, JSON.stringify(capture));
    const result = collectIdentityContinuityEvidence(capturePath, join(root, "invalid-ui"));
    expect(result.collected).toBe(false);
    expect(result.errors.join("\n")).toContain("structured UI evidence does not match fixture-only capture metadata");
  });

  it("rejects unsupported evidence kinds and keeps an existing pack immutable", () => {
    const { root, capturePath, capture } = captureFixture();
    const invalid = structuredClone(capture);
    invalid.evidence_sources[0].kind = "freeform_dump";
    writeFileSync(capturePath, JSON.stringify(invalid));
    const rejected = collectIdentityContinuityEvidence(capturePath, join(root, "invalid-kind"));
    expect(rejected.collected).toBe(false);
    expect(rejected.errors.join("\n")).toContain("unsupported evidence kind");

    writeFileSync(capturePath, JSON.stringify(capture));
    const output = join(root, "immutable");
    expect(collectIdentityContinuityEvidence(capturePath, output).collected).toBe(true);
    const original = readFileSync(join(output, "identity-continuity-pack.json"), "utf8");
    const repeated = collectIdentityContinuityEvidence(capturePath, output);
    expect(repeated.collected).toBe(false);
    expect(repeated.errors.join("\n")).toContain("already exists");
    expect(readFileSync(join(output, "identity-continuity-pack.json"), "utf8")).toBe(original);
  });

  it("fails closed for a non-object manifest and oversized evidence sources", () => {
    const { root, capturePath, capture } = captureFixture();
    writeFileSync(capturePath, JSON.stringify([]));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "array")).errors).toContain("capture manifest must be a JSON object");

    writeFileSync(capturePath, JSON.stringify(capture));
    writeFileSync(join(root, "source", "contracts.json"), JSON.stringify({ data: "x".repeat(2 * 1024 * 1024) }));
    const result = collectIdentityContinuityEvidence(capturePath, join(root, "oversized"));
    expect(result.collected).toBe(false);
    expect(result.errors.join("\n")).toContain("exceeds 2 MiB limit");
  });

  it("writes an explicit incomplete report and no pack when live captures are missing", () => {
    const { root, capturePath, capture } = captureFixture();
    capture.scenarios = capture.scenarios.filter((scenario) => scenario.id !== "cross_tenant_block");
    capture.evidence_sources = capture.evidence_sources.filter((source) => source.kind !== "graph_versions");
    writeFileSync(capturePath, JSON.stringify(capture));
    const output = join(root, "incomplete");
    const result = collectIdentityContinuityEvidence(capturePath, output);
    expect(result.collected).toBe(false);
    expect(result.errors.join("\n")).toContain("missing passing staging scenario evidence: cross_tenant_block");
    expect(result.errors.join("\n")).toContain("missing captured staging evidence kind: graph_versions");
    expect(existsSync(join(output, "identity-continuity-pack.json"))).toBe(false);
    expect(readFileSync(join(output, "collection-report.json"), "utf8")).toContain('"status": "incomplete"');
  });

  it("rejects path traversal and symlink escape without reading outside capture root", () => {
    const { root, capturePath, capture } = captureFixture();
    capture.evidence_sources[0].path = "../../outside.json";
    writeFileSync(capturePath, JSON.stringify(capture));
    const traversal = collectIdentityContinuityEvidence(capturePath, join(root, "traversal"));
    expect(traversal.errors.join("\n")).toContain("escapes capture directory");

    const external = join(root, "..", "outside-capture.json");
    writeFileSync(external, JSON.stringify({ value: "not allowed" }));
    capture.evidence_sources[0].path = "source/outside-link.json";
    symlinkSync(external, join(root, "source", "outside-link.json"));
    writeFileSync(capturePath, JSON.stringify(capture));
    const symlink = collectIdentityContinuityEvidence(capturePath, join(root, "symlink"));
    expect(symlink.errors.join("\n")).toContain("resolves outside capture directory");
    rmSync(external, { force: true });
  });

  it("requires every raw scenario artifact to match durable digest and run bindings", () => {
    const { root, capturePath, capture } = captureFixture();
    const missing = structuredClone(capture);
    missing.scenario_artifacts = missing.scenario_artifacts.filter((artifact) => artifact.scenario_id !== "cross_tenant_block");
    writeFileSync(capturePath, JSON.stringify(missing));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "missing-artifact")).errors.join("\n")).toContain("raw artifact evidence");

    const wrongDeployment = structuredClone(capture);
    wrongDeployment.scenario_run.deployment_id = "other-deployment";
    writeFileSync(capturePath, JSON.stringify(wrongDeployment));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "wrong-deployment")).errors.join("\n")).toContain("deployment does not match");

    const wrongTenant = structuredClone(capture);
    const artifactPath = join(root, wrongTenant.scenario_artifacts[0].path);
    const artifact = JSON.parse(readFileSync(artifactPath, "utf8"));
    artifact.tenant_ref = "other-tenant";
    writeFileSync(artifactPath, JSON.stringify(artifact) + "\n");
    writeFileSync(capturePath, JSON.stringify(wrongTenant));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "wrong-tenant")).errors.join("\n")).toContain("exact-byte SHA-256");
  });

  it("rejects duplicate artifact records, path traversal, and post-capture redaction or edits", () => {
    const { root, capturePath, capture } = captureFixture();
    const duplicate = structuredClone(capture);
    duplicate.scenario_artifacts.push({ ...duplicate.scenario_artifacts[0] });
    writeFileSync(capturePath, JSON.stringify(duplicate));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "duplicate-artifact")).errors.join("\n")).toContain("duplicate scenario id");

    const traversal = structuredClone(capture);
    traversal.scenario_artifacts[0].path = "../../outside.json";
    writeFileSync(capturePath, JSON.stringify(traversal));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "artifact-traversal")).errors.join("\n")).toContain("escapes capture directory");

    const artifactPath = join(root, capture.scenario_artifacts[0].path);
    const alteredArtifact = JSON.parse(readFileSync(artifactPath, "utf8"));
    alteredArtifact.api_trace = [{ email: "person@example.test" }];
    writeFileSync(artifactPath, JSON.stringify(alteredArtifact) + "\n");
    writeFileSync(capturePath, JSON.stringify(capture));
    expect(collectIdentityContinuityEvidence(capturePath, join(root, "redacted-after-digest")).errors.join("\n")).toContain("exact-byte SHA-256");
  });

  it("rejects an output evidence directory symlink that escapes the chosen output root", () => {
    const { root, capturePath } = captureFixture();
    const output = join(root, "escaped-output");
    const outside = join(root, "outside-output");
    mkdirSync(output);
    mkdirSync(outside);
    symlinkSync(outside, join(output, "evidence"));
    const result = collectIdentityContinuityEvidence(capturePath, output);
    expect(result.collected).toBe(false);
    expect(result.errors.join("\n")).toContain("output evidence directory resolves outside");
  });
});
