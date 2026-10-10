/**
 * Aether — Deployment failure classifier.
 *
 * Maps raw errors (thrown by our gates or by ethers/hardhat/RPC) into a small
 * set of actionable categories so operators get a clear next step instead of a
 * stack trace. Gate errors carry an `aetherCategory` tag which is honored first.
 */

"use strict";

const CATEGORIES = {
  AUDIT_GATE: "Mainnet audit gate blocked the deploy.",
  REGISTRY: "A required registry entry (oracle signer or contract) is missing.",
  DEFAULT_KEY: "A well-known development key/address was used on a live network.",
  CONFIG: "Missing or invalid configuration/environment variable.",
  INSUFFICIENT_FUNDS: "Deployer account has insufficient native balance for gas.",
  NONCE: "Transaction nonce conflict (pending/stuck tx or concurrent sender).",
  NETWORK: "RPC/network connectivity problem (unreachable, timeout, wrong chain).",
  REVERT: "On-chain execution reverted (constructor/require/custom error).",
  AUTH: "Authorization/signature problem (unauthorized sender or bad key).",
  UNKNOWN: "Unclassified failure — inspect the raw error below.",
};

function classifyError(err) {
  if (!err) return "UNKNOWN";
  if (err.aetherCategory && CATEGORIES[err.aetherCategory]) return err.aetherCategory;

  const code = String(err.code || "").toUpperCase();
  const msg = String(err.message || err).toLowerCase();

  if (code === "INSUFFICIENT_FUNDS" || msg.includes("insufficient funds")) {
    return "INSUFFICIENT_FUNDS";
  }
  if (code === "NONCE_EXPIRED" || msg.includes("nonce too low") || msg.includes("nonce has already been used") || msg.includes("replacement transaction underpriced")) {
    return "NONCE";
  }
  if (
    code === "NETWORK_ERROR" ||
    code === "TIMEOUT" ||
    code === "ECONNREFUSED" ||
    code === "ENOTFOUND" ||
    msg.includes("could not detect network") ||
    msg.includes("connect") ||
    msg.includes("timeout") ||
    msg.includes("failed to fetch")
  ) {
    return "NETWORK";
  }
  if (code === "CALL_EXCEPTION" || msg.includes("revert") || msg.includes("execution reverted") || msg.includes("custom error")) {
    return "REVERT";
  }
  if (msg.includes("unauthorized") || msg.includes("invalid signature") || msg.includes("sender doesn't have") || msg.includes("access") ) {
    return "AUTH";
  }
  if (msg.includes("env var") || msg.includes("required") || msg.includes("not a valid address") || msg.includes("missing")) {
    return "CONFIG";
  }
  return "UNKNOWN";
}

/**
 * Format a failure for the console: category, guidance, and the raw message.
 */
function describeFailure(err) {
  const cat = classifyError(err);
  const lines = [
    "─".repeat(60),
    `Deployment failed — category: ${cat}`,
    `  ${CATEGORIES[cat]}`,
    "",
    `  Detail: ${err && err.message ? err.message : String(err)}`,
    "─".repeat(60),
  ];
  return lines.join("\n");
}

module.exports = { CATEGORIES, classifyError, describeFailure };
