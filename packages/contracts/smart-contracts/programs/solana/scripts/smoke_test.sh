#!/usr/bin/env bash
# Post-deploy smoke test: confirm the deployed program is live and its state PDA
# is initialized and readable. Read-only except for an optional tiny claim probe.
#
# Usage: bash scripts/smoke_test.sh <cluster>       # cluster: localnet|testnet
#
# Required env for testnet:
#   AETHER_TESTNET_RPC_URL, AETHER_DEPLOYER_KEYPAIR
set -euo pipefail

CLUSTER="${1:-localnet}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

case "$CLUSTER" in
  localnet) RPC="${ANCHOR_PROVIDER_URL:-http://127.0.0.1:8899}" ;;
  testnet)  RPC="${AETHER_TESTNET_RPC_URL:?set AETHER_TESTNET_RPC_URL}" ;;
  *) echo "unknown cluster: $CLUSTER (use localnet|testnet)"; exit 2 ;;
esac

PROGRAM_ID="$(node -e "const r=require('./registry/program-registry.json');const e=r.deployments.find(d=>d.cluster==='$CLUSTER');if(!e){console.error('no registry entry for $CLUSTER');process.exit(1)}process.stdout.write(e.program_id)")"

echo "==> Smoke test on $CLUSTER (RPC=$RPC)"
echo "    Program id: $PROGRAM_ID"

echo "==> Program account is executable + shows upgrade authority"
solana program show "$PROGRAM_ID" --url "$RPC"

echo "==> State PDA is initialized and decodes"
npx ts-node scripts/register_program.ts --verify --cluster "$CLUSTER"

echo "==> Smoke test passed."
