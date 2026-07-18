/**
 * Aether — Network classification helpers (shared by deploy/verify/gas scripts)
 *
 * Networks are partitioned into three fail-closed tiers:
 *
 *   LOCAL    — in-process / localhost dev chains. No registry, no audit gate.
 *   TESTNET  — public testnets. Registries ARE enforced; audit gate is NOT.
 *   MAINNET  — everything else (real-value chains). Registries AND audit gate.
 *
 * Fail-closed rule: any network name that is NOT explicitly listed as LOCAL or
 * TESTNET is treated as MAINNET-class. A brand-new mainnet added to
 * hardhat.config.js therefore inherits the strictest gating by default, never
 * the weakest.
 */

"use strict";

/** Local development networks — no gating. */
const LOCAL_NETWORKS = new Set(["hardhat", "localhost"]);

/**
 * Public testnets known to hardhat.config.js. Registries are enforced here so
 * staging deploys exercise the same fail-closed path as production, but the
 * external-audit gate is intentionally NOT applied to testnets.
 */
const TESTNET_NETWORKS = new Set([
  "sepolia",
  "amoy",
  "arbitrumSepolia",
  "baseSepolia",
  "optimismSepolia",
]);

function isLocalNetwork(name) {
  return LOCAL_NETWORKS.has(name);
}

function isTestnetNetwork(name) {
  return TESTNET_NETWORKS.has(name);
}

/**
 * Mainnet-class = not local and not a known testnet. Unknown names fail closed
 * into this tier so they inherit the audit gate.
 */
function isMainnetNetwork(name) {
  return !isLocalNetwork(name) && !isTestnetNetwork(name);
}

/** Human-readable tier label for logging. */
function networkTier(name) {
  if (isLocalNetwork(name)) return "LOCAL";
  if (isTestnetNetwork(name)) return "TESTNET";
  return "MAINNET";
}

module.exports = {
  LOCAL_NETWORKS,
  TESTNET_NETWORKS,
  isLocalNetwork,
  isTestnetNetwork,
  isMainnetNetwork,
  networkTier,
};
