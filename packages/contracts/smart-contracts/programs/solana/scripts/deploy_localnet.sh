#!/usr/bin/env bash
# Deploy Aether Rewards to a local validator.
#
# Prerequisites (NOT installed in the authoring environment -- see audit/11):
#   solana, solana-test-validator, anchor, cargo-build-sbf, node/yarn
#
# Secrets: this script reads the deployer keypair and RPC URL from the
# environment. It NEVER embeds a key. For localnet the default Solana CLI
# keypair is used unless ANCHOR_WALLET is set.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

export ANCHOR_PROVIDER_URL="${ANCHOR_PROVIDER_URL:-http://127.0.0.1:8899}"
export ANCHOR_WALLET="${ANCHOR_WALLET:-$HOME/.config/solana/id.json}"

echo "==> Toolchain"
solana --version
anchor --version

echo "==> Ensuring a local validator is reachable at $ANCHOR_PROVIDER_URL"
if ! solana --url "$ANCHOR_PROVIDER_URL" cluster-version >/dev/null 2>&1; then
  echo "No validator reachable. Start one with:"
  echo "    solana-test-validator --reset"
  exit 1
fi

echo "==> Syncing declared program id with the deploy keypair"
# Generates target/deploy/aether_rewards-keypair.json on first run and rewrites
# declare_id!/Anchor.toml to match. The keypair is gitignored.
anchor keys sync

echo "==> Building (SBF)"
anchor build

echo "==> Deploying to localnet"
anchor deploy --provider.cluster "$ANCHOR_PROVIDER_URL" --provider.wallet "$ANCHOR_WALLET"

PROGRAM_ID="$(solana address -k target/deploy/aether_rewards-keypair.json)"
echo "==> Deployed program id: $PROGRAM_ID"

echo "==> Recording program id into the registry (localnet cluster)"
node --version >/dev/null 2>&1 && \
  npx ts-node scripts/register_program.ts --cluster localnet --program-id "$PROGRAM_ID" || \
  echo "(skip registry write: node/ts-node unavailable)"

echo "==> Done. Next: initialize via 'anchor run initialize' or the smoke test."
