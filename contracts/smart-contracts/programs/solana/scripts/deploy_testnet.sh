#!/usr/bin/env bash
# Deploy Aether Rewards to Solana testnet (credential-gated).
#
# This script is CREDENTIAL-WAITING: it will refuse to run unless the required
# secret references are present in the environment. It never embeds a key.
#
# Required environment (inject from your secret manager / CI secrets):
#   AETHER_TESTNET_RPC_URL        e.g. https://api.testnet.solana.com (or a private RPC)
#   AETHER_DEPLOYER_KEYPAIR       absolute path to the deployer keypair json (mounted secret)
#   AETHER_UPGRADE_AUTHORITY      pubkey that must own upgrade authority (policy check)
# Optional:
#   AETHER_ORACLE_PUBKEY          oracle Ed25519 pubkey to initialize with
#   AETHER_CHAIN_ID               defaults to 102 (testnet) per aether_domain::chain_id
#
# mainnet-real-value note: this script targets TESTNET only. Mainnet deployment
# is BLOCKED pending recorded external-audit evidence (see audit/08, audit/10).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "ERROR: required secret reference '$name' is not set. Aborting." >&2
    exit 2
  fi
}

require_env AETHER_TESTNET_RPC_URL
require_env AETHER_DEPLOYER_KEYPAIR
require_env AETHER_UPGRADE_AUTHORITY

if [ ! -f "$AETHER_DEPLOYER_KEYPAIR" ]; then
  echo "ERROR: deployer keypair file not found at \$AETHER_DEPLOYER_KEYPAIR" >&2
  exit 2
fi

export ANCHOR_PROVIDER_URL="$AETHER_TESTNET_RPC_URL"
export ANCHOR_WALLET="$AETHER_DEPLOYER_KEYPAIR"
CHAIN_ID="${AETHER_CHAIN_ID:-102}"

echo "==> Testnet deploy"
solana --version
anchor --version
echo "    RPC:            $ANCHOR_PROVIDER_URL"
echo "    Deployer:       $(solana address -k "$AETHER_DEPLOYER_KEYPAIR")"
echo "    Upgrade auth:   $AETHER_UPGRADE_AUTHORITY (policy target)"
echo "    Chain id:       $CHAIN_ID"

DEPLOYER_BAL="$(solana --url "$ANCHOR_PROVIDER_URL" balance -k "$AETHER_DEPLOYER_KEYPAIR" | awk '{print $1}')"
echo "    Deployer bal:   $DEPLOYER_BAL SOL"

echo "==> Sync program id + build (SBF, reproducible profile)"
anchor keys sync
anchor build

echo "==> Deploying to testnet"
anchor deploy --provider.cluster "$ANCHOR_PROVIDER_URL" --provider.wallet "$ANCHOR_WALLET"
PROGRAM_ID="$(solana address -k target/deploy/aether_rewards-keypair.json)"
echo "    Program id:     $PROGRAM_ID"

echo "==> Enforcing upgrade-authority policy (see registry/upgrade-authority-policy.md)"
# Move upgrade authority to the governance-controlled authority. On mainnet this
# MUST be a multisig / squads authority; on testnet a hot key is acceptable.
solana program set-upgrade-authority "$PROGRAM_ID" \
  --new-upgrade-authority "$AETHER_UPGRADE_AUTHORITY" \
  --url "$ANCHOR_PROVIDER_URL" \
  -k "$AETHER_DEPLOYER_KEYPAIR"

echo "==> Verifying upgrade authority landed"
solana program show "$PROGRAM_ID" --url "$ANCHOR_PROVIDER_URL"

echo "==> Recording into registry (testnet cluster)"
npx ts-node scripts/register_program.ts \
  --cluster testnet \
  --program-id "$PROGRAM_ID" \
  --upgrade-authority "$AETHER_UPGRADE_AUTHORITY" \
  --chain-id "$CHAIN_ID"

echo "==> Testnet deploy complete. Run: yarn smoke:testnet"
