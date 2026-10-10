---
title: Derivatives Connector Contract
slug: source-of-truth/derivatives_connector_contract
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Derivatives Connector Contract

PR2 introduces a read-only connector interface for derivatives venues and tenant imports. The contract exposes venue description, connection testing, market/account/fill fetches, account streams, normalization, checkpoints, and health without adding any trade submission, transfer, withdrawal, key-management, or mutation method.

Hyperliquid is the reference production-shaped adapter. In this PR it normalizes Bronze `raw_fill` observations into Silver fill facts with deterministic idempotency keys and fixed-precision decimals. Generic import accepts CSV, JSON, and NDJSON rows, supports dry-run validation, row-level quarantine errors, mapping versions, and batch idempotency.

Credential validation rejects mutating scopes such as write, trading, order write, transfers, withdrawals, key management, and admin scope. Credentials remain references handled by the existing connector/BYOK control plane; this domain code never stores or returns secret material.
