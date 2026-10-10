/**
 * Aether — Mainnet external-audit gate.
 *
 * Deploying to a MAINNET-class network fails closed unless valid external-audit
 * evidence exists at audit/AUDIT_EVIDENCE.json. Testnets and local networks are
 * unaffected.
 *
 * The evidence file is intentionally NOT committed to the repo — its presence is
 * the switch that unblocks real-value deployment, so it must be added by a human
 * only after a real audit sign-off. audit/AUDIT_EVIDENCE.template.json documents
 * the required shape.
 *
 * Required, non-empty fields (any missing/empty/false => gate fails):
 *   auditor.name                — auditing individual/firm
 *   report.sha256               — 64-hex digest of the final report
 *   report.file                 — report filename (hash is verified if present on disk)
 *   scope.commit                — audited git commit / tag
 *   scope.contracts[]           — non-empty list of audited source paths
 *   signoff.approved === true   — explicit boolean sign-off
 *   signoff.approver            — who approved release
 */

"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { isMainnetNetwork } = require("./networks");

const AUDIT_DIR = path.resolve(__dirname, "..", "..", "audit");
const EVIDENCE_PATH = path.join(AUDIT_DIR, "AUDIT_EVIDENCE.json");

function _isHex64(s) {
  return typeof s === "string" && /^[0-9a-fA-F]{64}$/.test(s.trim());
}

/**
 * Validate an already-parsed evidence object. Returns { ok, errors[] }.
 * Exposed separately so tests / CI can validate without touching the gate.
 */
function validateEvidence(ev, { auditDir = AUDIT_DIR } = {}) {
  const errors = [];
  if (!ev || typeof ev !== "object") {
    return { ok: false, errors: ["evidence is not a JSON object"] };
  }
  const auditor = ev.auditor || {};
  const report = ev.report || {};
  const scope = ev.scope || {};
  const signoff = ev.signoff || {};

  if (!auditor.name || String(auditor.name).trim() === "") {
    errors.push("auditor.name is missing/empty");
  }
  if (!_isHex64(report.sha256 || "")) {
    errors.push("report.sha256 must be a 64-character hex digest");
  }
  if (!report.file || String(report.file).trim() === "") {
    errors.push("report.file is missing/empty");
  }
  if (!scope.commit || String(scope.commit).trim() === "") {
    errors.push("scope.commit is missing/empty");
  }
  if (!Array.isArray(scope.contracts) || scope.contracts.length === 0) {
    errors.push("scope.contracts must be a non-empty array");
  }
  if (signoff.approved !== true) {
    errors.push("signoff.approved must be boolean true");
  }
  if (!signoff.approver || String(signoff.approver).trim() === "") {
    errors.push("signoff.approver is missing/empty");
  }

  // If the report file is present on disk, its hash MUST match the claim.
  if (report.file && _isHex64(report.sha256 || "")) {
    const reportPath = path.isAbsolute(report.file)
      ? report.file
      : path.join(auditDir, report.file);
    if (fs.existsSync(reportPath)) {
      const digest = crypto
        .createHash("sha256")
        .update(fs.readFileSync(reportPath))
        .digest("hex");
      if (digest.toLowerCase() !== String(report.sha256).trim().toLowerCase()) {
        errors.push(
          `report.sha256 mismatch: file ${report.file} hashes to ${digest} ` +
            `but evidence claims ${report.sha256}`
        );
      }
    }
  }

  return { ok: errors.length === 0, errors };
}

/**
 * Enforce the audit gate for `network`. No-op on non-mainnet networks.
 * Throws (AUDIT_GATE category) when mainnet and evidence is absent/invalid.
 */
function assertAuditEvidence(network) {
  if (!isMainnetNetwork(network)) return; // testnets + local: unaffected

  if (!fs.existsSync(EVIDENCE_PATH)) {
    const e = new Error(
      `MAINNET AUDIT GATE: refusing to deploy to '${network}'. No external-audit ` +
        `evidence found at ${_rel(EVIDENCE_PATH)}. Mainnet real-value activation ` +
        `stays BLOCKED until a completed audit sign-off is recorded there ` +
        `(see audit/AUDIT_EVIDENCE.template.json).`
    );
    e.aetherCategory = "AUDIT_GATE";
    throw e;
  }

  let ev;
  try {
    ev = JSON.parse(fs.readFileSync(EVIDENCE_PATH, "utf8"));
  } catch (err) {
    const e = new Error(
      `MAINNET AUDIT GATE: ${_rel(EVIDENCE_PATH)} is not valid JSON: ${err.message}`
    );
    e.aetherCategory = "AUDIT_GATE";
    throw e;
  }

  const { ok, errors } = validateEvidence(ev);
  if (!ok) {
    const e = new Error(
      `MAINNET AUDIT GATE: audit evidence at ${_rel(EVIDENCE_PATH)} is invalid ` +
        `for '${network}':\n  - ${errors.join("\n  - ")}`
    );
    e.aetherCategory = "AUDIT_GATE";
    throw e;
  }
}

function _rel(p) {
  return path.relative(path.resolve(__dirname, "..", ".."), p);
}

module.exports = {
  EVIDENCE_PATH,
  validateEvidence,
  assertAuditEvidence,
};
