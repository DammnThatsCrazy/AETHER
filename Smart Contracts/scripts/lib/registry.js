/**
 * Aether — Deploy-time registries (oracle signers + contract addresses).
 *
 * Two JSON registries under deploy/registry/ are the canonical allowlists:
 *
 *   oracle_signers.json  — per-network allowlist of authorized ORACLE signer
 *                          addresses. Deploy fails closed on non-local networks
 *                          unless the oracle being wired in is registered here.
 *
 *   contracts.json       — per-network record of deployed contract addresses.
 *                          Post-deploy verification fails closed on non-local
 *                          networks unless the target address is registered
 *                          here. deploy.js writes new addresses back after a
 *                          successful deploy so the record stays authoritative.
 *
 * Both registries hold only PUBLIC addresses — never private keys.
 *
 * Fail-closed semantics: a missing file, a missing network entry, or an empty
 * allowlist all cause enforcement to reject. Local networks (hardhat/localhost)
 * bypass enforcement entirely so dev loops stay frictionless.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const { isLocalNetwork } = require("./networks");

const REGISTRY_DIR = path.resolve(__dirname, "..", "..", "deploy", "registry");
const ORACLE_REGISTRY_PATH = path.join(REGISTRY_DIR, "oracle_signers.json");
const CONTRACT_REGISTRY_PATH = path.join(REGISTRY_DIR, "contracts.json");

function _readJson(p) {
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (err) {
    const e = new Error(`Registry file ${p} is not valid JSON: ${err.message}`);
    e.aetherCategory = "REGISTRY";
    throw e;
  }
}

function _lc(x) {
  return String(x || "").trim().toLowerCase();
}

/** Return the array of registered oracle addresses for a network (lowercased). */
function getRegisteredOracles(network) {
  const data = _readJson(ORACLE_REGISTRY_PATH);
  if (!data || !data.networks || !Array.isArray(data.networks[network])) return [];
  return data.networks[network].map(_lc).filter(Boolean);
}

/** Return the map of registered contracts for a network. */
function getRegisteredContracts(network) {
  const data = _readJson(CONTRACT_REGISTRY_PATH);
  if (!data || !data.networks || typeof data.networks[network] !== "object") return {};
  return data.networks[network] || {};
}

/**
 * Enforce that `oracleAddress` is a registered signer for `network`.
 * No-op on local networks. Throws (REGISTRY category) otherwise.
 */
function assertOracleRegistered(network, oracleAddress) {
  if (isLocalNetwork(network)) return;
  const allow = getRegisteredOracles(network);
  if (allow.length === 0) {
    const e = new Error(
      `Oracle-signer registry has no entries for network '${network}'. ` +
        `Add the authorized oracle address to ${_rel(ORACLE_REGISTRY_PATH)} ` +
        `under networks.${network} (reviewed change) before deploying.`
    );
    e.aetherCategory = "REGISTRY";
    throw e;
  }
  if (!allow.includes(_lc(oracleAddress))) {
    const e = new Error(
      `Oracle ${oracleAddress} is NOT registered for network '${network}'. ` +
        `Registered: [${allow.join(", ")}]. Add it to ` +
        `${_rel(ORACLE_REGISTRY_PATH)} (reviewed change) or fix ORACLE_ADDRESS.`
    );
    e.aetherCategory = "REGISTRY";
    throw e;
  }
}

/**
 * Enforce that `address` is a registered contract for `network`.
 * No-op on local networks. Throws (REGISTRY category) otherwise.
 * `label` is used only for the error message (e.g. "AnalyticsRewards").
 */
function assertContractRegistered(network, address, label) {
  if (isLocalNetwork(network)) return;
  const contracts = getRegisteredContracts(network);
  const known = Object.values(contracts).map(_lc).filter(Boolean);
  if (known.length === 0) {
    const e = new Error(
      `Contract registry has no entries for network '${network}'. ` +
        `Register ${label || "the deployed contract"} address in ` +
        `${_rel(CONTRACT_REGISTRY_PATH)} under networks.${network} before verifying.`
    );
    e.aetherCategory = "REGISTRY";
    throw e;
  }
  if (!known.includes(_lc(address))) {
    const e = new Error(
      `${label || "Contract"} ${address} is NOT registered for network ` +
        `'${network}'. Registered: [${known.join(", ")}]. Update ` +
        `${_rel(CONTRACT_REGISTRY_PATH)} (reviewed change) or fix the address.`
    );
    e.aetherCategory = "REGISTRY";
    throw e;
  }
}

/**
 * Record deployed contract addresses for a network into contracts.json.
 * Used by deploy.js after a successful non-local deploy so the verify step and
 * future runs have an authoritative record. Creates the file/entry if absent.
 * `entries` is an object like { AnalyticsRewards: "0x..", RewardRegistry: "0x.." }.
 */
function recordContracts(network, entries) {
  let data = _readJson(CONTRACT_REGISTRY_PATH);
  if (!data || typeof data !== "object") {
    data = { _comment: CONTRACT_REGISTRY_COMMENT, networks: {} };
  }
  if (!data.networks) data.networks = {};
  data.networks[network] = { ...(data.networks[network] || {}), ...entries };
  fs.mkdirSync(REGISTRY_DIR, { recursive: true });
  fs.writeFileSync(CONTRACT_REGISTRY_PATH, JSON.stringify(data, null, 2) + "\n");
  return CONTRACT_REGISTRY_PATH;
}

const CONTRACT_REGISTRY_COMMENT =
  "Canonical record of deployed Aether contract addresses per Hardhat network. " +
  "post_deploy_verify.js fails closed outside local networks unless the target " +
  "address is registered here. deploy.js appends new addresses automatically; " +
  "review the diff before committing.";

function _rel(p) {
  return path.relative(path.resolve(__dirname, "..", ".."), p);
}

module.exports = {
  ORACLE_REGISTRY_PATH,
  CONTRACT_REGISTRY_PATH,
  getRegisteredOracles,
  getRegisteredContracts,
  assertOracleRegistered,
  assertContractRegistered,
  recordContracts,
};
