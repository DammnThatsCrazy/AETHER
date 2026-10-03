import { createHash } from "crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it } from "vitest";
import { buildIdentityContinuityPack, REQUIRED_IDENTITY_CONTINUITY_SCENARIOS, REQUIRED_PROJECTION_OUTCOMES, validateIdentityContinuityPack } from "./identity-continuity-pack";

const roots: string[] = [];
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "aether-identity-proof-"));
  roots.push(root);
  mkdirSync(join(root, "evidence"));
  const evidence = [] as Array<{ id: string; kind: string; path: string; sha256: string }>;
  const addEvidence = (id: string, kind: string) => {
    const bytes = JSON.stringify({ collected: true, source: "staging-runtime", evidence_id: id, kind });
    const path = `evidence/${id}.json`;
    writeFileSync(join(root, path), bytes);
    evidence.push({ id, kind, path, sha256: createHash("sha256").update(bytes).digest("hex") });
    return id;
  };
  const contractEvidence = addEvidence("contracts", "contract_inventory");
  const scenarioEvidence = addEvidence("scenarios", "scenario_result");
  const graphEvidence = addEvidence("graph", "graph_versions");
  const jobEvidence = addEvidence("jobs", "restatement_job");
  const projectionEvidence = addEvidence("projections", "projection_outcome");
  const flagEvidence = addEvidence("flags", "feature_flags");
  const scenarioRun = { execution_id: "execution-42", tenant_ref: `tenant:${"c".repeat(32)}`, deployment_id: "deploy-123" };
  const scenarios = REQUIRED_IDENTITY_CONTINUITY_SCENARIOS.map((id, index) => {
    const bytes = `${JSON.stringify({ scenario_id: id, execution_id: scenarioRun.execution_id, tenant_ref: scenarioRun.tenant_ref,
      outcome: "passed", assertions_failed: 0 })}\n`;
    const artifactId = `scenario-artifact-${id}`;
    const path = `evidence/${artifactId}.json`;
    writeFileSync(join(root, path), bytes);
    evidence.push({ id: artifactId, kind: "scenario_artifact", path, sha256: createHash("sha256").update(bytes).digest("hex") });
    return { id, status: "passed", evidence_id: scenarioEvidence, artifact_evidence_id: artifactId,
      evidence_sha256: createHash("sha256").update(bytes).digest("hex"), execution_ref: `execution-hash-${index}`, executed_at: "2026-09-27T16:55:00Z" };
  });
  const scenarioSummary = JSON.stringify({ payload: { scenarios: scenarios.map(({ id, status, evidence_sha256, execution_ref }) => ({ id, status, evidence_sha256, execution_ref })) } });
  writeFileSync(join(root, "evidence", "scenarios.json"), scenarioSummary);
  evidence.find((reference) => reference.id === scenarioEvidence)!.sha256 = createHash("sha256").update(scenarioSummary).digest("hex");
  const pack = {
    schema_version: "1.0.0",
    proof_id: "late-binding-staging-2026-09-27",
    generated_at: "2026-09-27T17:00:00Z",
    commit: { sha: "a".repeat(40), branch: "identity-continuity" },
    environment: { name: "staging", deployment_id: "deploy-123", observed_at: "2026-09-27T16:59:00Z" },
    scenario_run: scenarioRun,
    evidence,
    contract_inventory: { evidence_id: contractEvidence, required_contract_ids: ["event-envelope", "identity-evidence"], observed_contract_ids: ["event-envelope", "identity-evidence"] },
    scenarios,
    graph_versions: [{ tenant_id: "tenant-test", graph: "identity", before: "graph-10", after: "graph-11", observed_at: "2026-09-27T16:56:00Z", evidence_id: graphEvidence }],
    restatement_jobs: [{ tenant_id: "tenant-test", job_id: "job-456", status: "succeeded", projection: "profile_360", source_graph_version: "graph-10", resulting_graph_version: "graph-11", completed_at: "2026-09-27T16:58:00Z", evidence_id: jobEvidence }],
    projection_outcomes: Object.entries(REQUIRED_PROJECTION_OUTCOMES).map(([projection, status]) => ({ projection, status, evidence_id: projectionEvidence })),
    feature_flags: { evidence_id: flagEvidence, values: { IDENTITY_CONTINUITY: true }, required_enabled: ["IDENTITY_CONTINUITY"] },
    ui_evidence: [] as Array<Record<string, unknown>>,
  };
  for (const surface of ["activation", "review_queue"] as const) {
    const id = surface === "activation" ? "a".repeat(24) : "b".repeat(24);
    const routes = surface === "activation"
      ? ["/v1/me", "/v1/capabilities", "/v1/admin/identity/activation-status"]
      : ["/v1/me", "/v1/capabilities", "/v1/admin/identity/review-queue"];
    const observations = {
      schema_version: "aether.identity-ui-evidence.v2", evidence_class: "ui_live_staging", api_mode: "authenticated_real_backend",
      live_staging_claim: true, test_id: `live ${surface}`, surface, tenant_ref: scenarioRun.tenant_ref,
      deployment_id: scenarioRun.deployment_id, captured_at: "2026-09-27T17:00:00Z",
      page_origin: "https://app.staging.example", api_origin: "https://api.staging.example",
      api_observations: routes.map((path) => ({ method: "GET", path, status: 200 })),
    };
    const structuredBytes = Buffer.from(JSON.stringify(observations));
    const screenshotBytes = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 4, 5, 6]);
    const structuredId = `ui-${surface}-observations`;
    const screenshotId = `ui-${surface}-screenshot`;
    const structuredPath = `evidence/${structuredId}.json`;
    const screenshotPath = `evidence/${screenshotId}.png`;
    writeFileSync(join(root, structuredPath), structuredBytes);
    writeFileSync(join(root, screenshotPath), screenshotBytes);
    evidence.push(
      { id: structuredId, kind: "ui_e2e", path: structuredPath, sha256: createHash("sha256").update(structuredBytes).digest("hex") },
      { id: screenshotId, kind: "ui_e2e_screenshot", path: screenshotPath, sha256: createHash("sha256").update(screenshotBytes).digest("hex") },
    );
    pack.ui_evidence.push({
      id, surface, test_id: observations.test_id, tenant_ref: scenarioRun.tenant_ref, deployment_id: scenarioRun.deployment_id,
      evidence_class: "ui_live_staging", api_mode: "authenticated_real_backend", live_staging_claim: true,
      captured_at: observations.captured_at, structured_evidence_id: structuredId, screenshot_evidence_id: screenshotId,
    });
  }
  const inputPath = join(root, "evidence-manifest.json");
  writeFileSync(inputPath, JSON.stringify(pack));
  return { root, inputPath, pack };
}

afterEach(() => roots.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true })));

describe("identity continuity proof pack", () => {
  it("builds a pack only from complete collected evidence and validates its referenced bytes", () => {
    const { inputPath, pack } = fixture();
    const outputPath = join(inputPath, "..", "proof-pack.json");
    expect(buildIdentityContinuityPack(inputPath, outputPath)).toEqual({ valid: true, errors: [] });
    expect(validateIdentityContinuityPack(JSON.parse(readFileSync(outputPath, "utf8")), outputPath)).toEqual({ valid: true, errors: [] });
  });

  it("rejects absent contract, scenario, graph, restatement, or flag evidence", () => {
    const { inputPath, pack } = fixture();
    const invalid = structuredClone(pack);
    invalid.contract_inventory.observed_contract_ids = ["event-envelope"];
    invalid.scenarios[0].status = "skipped";
    invalid.restatement_jobs[0].status = "pending";
    invalid.feature_flags.values.IDENTITY_CONTINUITY = false;
    const result = validateIdentityContinuityPack(invalid, inputPath);
    expect(result.valid).toBe(false);
    expect(result.errors.join("\n")).toContain("identity-evidence");
    expect(result.errors.join("\n")).toContain("timestamped passing result");
    expect(result.errors.join("\n")).toContain("successful job record");
    expect(result.errors.join("\n")).toContain("disabled: IDENTITY_CONTINUITY");
  });

  it("requires every blueprint scenario and keeps unsupported Syndicates explicit", () => {
    const { inputPath, pack } = fixture();
    const missing = structuredClone(pack);
    missing.scenarios = missing.scenarios.filter((scenario) => scenario.id !== "cross_tenant_block");
    const missingResult = validateIdentityContinuityPack(missing, inputPath);
    expect(missingResult.errors.join("\n")).toContain("mandatory scenario result is absent: cross_tenant_block");

    const falselyPassed = structuredClone(pack);
    falselyPassed.projection_outcomes.find((item) => item.projection === "syndicates")!.status = "completed";
    const projectionResult = validateIdentityContinuityPack(falselyPassed, inputPath);
    expect(projectionResult.errors.join("\n")).toContain("projection syndicates must be explicitly unsupported");
  });

  it("rejects tampered or missing evidence bytes and graph/job version inconsistencies", () => {
    const { inputPath, pack, root } = fixture();
    writeFileSync(join(root, "evidence", "jobs.json"), "tampered");
    const badTransition = structuredClone(pack);
    badTransition.restatement_jobs[0].resulting_graph_version = "graph-12";
    const result = validateIdentityContinuityPack(badTransition, inputPath);
    expect(result.valid).toBe(false);
    expect(result.errors.join("\n")).toContain("SHA-256 does not match");
    expect(result.errors.join("\n")).toContain("no matching tenant graph version transition");
  });

  it("rejects evidence paths that escape the pack directory", () => {
    const { inputPath, pack } = fixture();
    const escaped = structuredClone(pack);
    escaped.evidence[0].path = "../outside.json";
    const result = validateIdentityContinuityPack(escaped, inputPath);
    expect(result.valid).toBe(false);
    expect(result.errors.join("\n")).toContain("must stay beneath the pack directory");
  });

  it("binds every scenario to unique exact-byte artifact, execution, tenant, and deployment evidence", () => {
    const { inputPath, pack } = fixture();
    const duplicateArtifact = structuredClone(pack);
    duplicateArtifact.scenarios[1].artifact_evidence_id = duplicateArtifact.scenarios[0].artifact_evidence_id;
    const duplicateResult = validateIdentityContinuityPack(duplicateArtifact, inputPath);
    expect(duplicateResult.errors.join("\n")).toContain("scenario artifact evidence is duplicated");

    const wrongExecution = structuredClone(pack);
    wrongExecution.scenario_run.execution_id = "different-execution";
    expect(validateIdentityContinuityPack(wrongExecution, inputPath).errors.join("\n")).toContain("execution does not match");

    const wrongTenant = structuredClone(pack);
    wrongTenant.scenario_run.tenant_ref = "different-tenant";
    expect(validateIdentityContinuityPack(wrongTenant, inputPath).errors.join("\n")).toContain("tenant does not match");

    const wrongDeployment = structuredClone(pack);
    wrongDeployment.scenario_run.deployment_id = "different-deployment";
    expect(validateIdentityContinuityPack(wrongDeployment, inputPath).errors.join("\n")).toContain("deployment does not match");
  });

  it("rejects a symlink that escapes the pack directory", () => {
    const { inputPath, pack, root } = fixture();
    const externalPath = join(root, "..", `${root.split("/").pop()}-external.json`);
    const bytes = "external runtime evidence";
    writeFileSync(externalPath, bytes);
    symlinkSync(externalPath, join(root, "evidence", "external-link.json"));
    const escaped = structuredClone(pack);
    escaped.evidence[0].path = "evidence/external-link.json";
    escaped.evidence[0].sha256 = createHash("sha256").update(bytes).digest("hex");
    const result = validateIdentityContinuityPack(escaped, inputPath);
    rmSync(externalPath, { force: true });
    expect(result.valid).toBe(false);
    expect(result.errors.join("\n")).toContain("resolves outside the pack directory");
  });

  it("copies and revalidates evidence when building a pack in another output directory", () => {
    const { inputPath, root } = fixture();
    const outputDirectory = join(root, "portable-output");
    const output = join(outputDirectory, "proof-pack.json");
    const result = buildIdentityContinuityPack(inputPath, output);
    expect(result).toEqual({ valid: true, errors: [] });
    const built = JSON.parse(readFileSync(output, "utf8"));
    expect(built.evidence[0].path).toContain("evidence/");
    expect(validateIdentityContinuityPack(built, output)).toEqual({ valid: true, errors: [] });
    expect(readFileSync(join(outputDirectory, built.evidence[0].path), "utf8")).toBeTruthy();
  });

  it("copies raw fixture-only UI screenshots and preserves their non-staging classification", () => {
    const { inputPath, root, pack } = fixture();
    const screenshotBytes = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 4, 5, 6]);
    const observations = {
      schema_version: "aether.identity-ui-evidence.v1", evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: false,
      test_id: "activation fixture screen", surface: "activation", tenant_ref: "tenant_identity_e2e_a",
    };
    const structuredBytes = Buffer.from(JSON.stringify(observations));
    writeFileSync(join(root, "evidence", "ui-observations.json"), structuredBytes);
    writeFileSync(join(root, "evidence", "ui-screenshot.png"), screenshotBytes);
    pack.evidence.push(
      { id: "ui-observations", kind: "ui_e2e", path: "evidence/ui-observations.json", sha256: createHash("sha256").update(structuredBytes).digest("hex") },
      { id: "ui-screenshot", kind: "ui_e2e_screenshot", path: "evidence/ui-screenshot.png", sha256: createHash("sha256").update(screenshotBytes).digest("hex") },
    );
    pack.ui_evidence.push({
      id: "ui-activation-1", surface: "activation", test_id: observations.test_id,
      tenant_ref: observations.tenant_ref, evidence_class: "ui_fixture_only",
      api_mode: "playwright_route_fixture", live_staging_claim: false,
      captured_at: "2026-09-27T18:00:00Z", structured_evidence_id: "ui-observations",
      screenshot_evidence_id: "ui-screenshot",
    });
    writeFileSync(inputPath, JSON.stringify(pack));
    const output = join(root, "ui-portable", "identity-continuity-pack.json");
    expect(buildIdentityContinuityPack(inputPath, output)).toEqual({ valid: true, errors: [] });
    const built = JSON.parse(readFileSync(output, "utf8"));
    const fixtureUi = built.ui_evidence.find((item: { evidence_class: string }) => item.evidence_class === "ui_fixture_only");
    expect(fixtureUi).toMatchObject({ evidence_class: "ui_fixture_only", live_staging_claim: false });
    const pngRef = built.evidence.find((item: { kind: string }) => item.kind === "ui_e2e_screenshot");
    expect(readFileSync(join(root, "ui-portable", pngRef.path))).toEqual(screenshotBytes);
    const overstated = structuredClone(built);
    overstated.ui_evidence.find((item: { evidence_class: string }) => item.evidence_class === "ui_fixture_only").live_staging_claim = true;
    expect(validateIdentityContinuityPack(overstated, output).errors.join("\n")).toContain("invalid fixture or live staging provenance");
  });

  it("returns validation errors for malformed JSON shapes instead of throwing", () => {
    const { inputPath } = fixture();
    const result = validateIdentityContinuityPack({ schema_version: "1.0.0", scenarios: [null], graph_versions: [null], restatement_jobs: [null] }, inputPath);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });
});
