# Aether Smart Contract Security Audit (May 24, 2026)

## 1) Executive Summary
This review covered all Solidity contracts in `Smart Contracts/contracts`:
- `AnalyticsRewards.sol`
- `RewardRegistry.sol`
- `interfaces/IAnalyticsRewards.sol`
- `test/MockERC20.sol`

The protocol is relatively small and mostly centralized around privileged roles (`DEFAULT_ADMIN_ROLE`, `CAMPAIGN_MANAGER_ROLE`, `ORACLE_ROLE`, and `REGISTRY_MANAGER_ROLE`). The highest-impact issue found is a **functional/security mismatch in oracle introspection** where `getOracleAddress()` always returns `address(0)`, creating a high-risk operational failure mode for off-chain signing/monitoring infrastructure and potentially leading to reward distribution outages or trust-boundary confusion.

No direct on-chain unauthorized-withdrawal primitive was found under the assumed trust model (honest admin, honest oracle). However, **compromised privileged keys have full fund-drain blast radius** by design.

## 2) Protocol Architecture Overview
### Core components
1. **AnalyticsRewards**
   - Custodies ERC-20 rewards.
   - Verifies EIP-191 signatures from `ORACLE_ROLE` for claims.
   - Tracks per-campaign budget and nonce replay protection.
   - Supports campaign create/pause/resume/addBudget.
   - Emergency pause and emergency withdrawal by admin.

2. **RewardRegistry**
   - Metadata registry for action types and campaign catalog.
   - Not enforcement-coupled to `AnalyticsRewards` claims.

3. **IAnalyticsRewards**
   - Interface for claim, campaign management, and read methods.

### Inheritance graph
- `AnalyticsRewards` -> `IAnalyticsRewards`, `AccessControl`, `Pausable`, `ReentrancyGuard`
- `RewardRegistry` -> `AccessControl`
- `MockERC20` -> `ERC20`

## 3) Trust Model Summary
- **Admin trust**: `DEFAULT_ADMIN_ROLE` can pause and withdraw all funds (when paused). This is full custody authority.
- **Oracle trust**: Any address with `ORACLE_ROLE` can authorize arbitrary payouts (subject to budget/nonce/expiry), including setting arbitrary `amount` values.
- **Campaign manager trust**: Can create, pause/resume, and fund campaigns; cannot directly withdraw, but controls reward-availability state.
- **Registry manager trust**: Can mutate metadata only; no direct payout authority.

## 4) Privileged Role Matrix
| Role | Contract | Powers | Risk |
|---|---|---|---|
| `DEFAULT_ADMIN_ROLE` | AnalyticsRewards | Grant/revoke roles, pause/unpause, emergency withdrawals | Critical custody + governance |
| `ORACLE_ROLE` | AnalyticsRewards | Signature authorization for claims | Critical payout integrity |
| `CAMPAIGN_MANAGER_ROLE` | AnalyticsRewards | Create/fund/pause/resume campaigns | High operational control |
| `DEFAULT_ADMIN_ROLE` | RewardRegistry | Role admin | Medium (metadata governance) |
| `REGISTRY_MANAGER_ROLE` | RewardRegistry | Register/update actions/campaign metadata | Medium |

## 5) Attack Surface Summary
- `claimReward(...)` external + signature parsing + token transfer.
- All role-gated external mutators.
- Emergency withdrawals (paused-only).
- External token interactions via `SafeERC20`.
- Off-chain signer/key management and signer-discovery tooling.

## 6) Findings by Severity

### Finding 1: `getOracleAddress()` always returns zero and violates security/operational assumptions
**Severity:** High  
**Affected Contracts:** `Smart Contracts/contracts/AnalyticsRewards.sol` (`getOracleAddress`)  
**Confidence:** High

#### Vulnerability Description
`getOracleAddress()` always returns `address(0)` despite the interface/documentation indicating it should return the current oracle. This creates an API-level trust-boundary failure: off-chain systems (claim generators, monitors, health checks, dashboards, relayers) can incorrectly assume no configured oracle or use fallback behavior.

Because signature verification is authoritative in `claimReward`, this mismatch causes **cross-system desynchronization** between on-chain truth (`hasRole(ORACLE_ROLE, x)`) and external control-plane assumptions.

#### Impact
- Operational outage risk in reward claiming if clients rely on this getter.
- Incorrect monitoring/alerting for key rotation or oracle compromise.
- Security tooling may mis-detect oracle state and miss real incidents.

#### Proof of Concept
1. Deploy with non-zero `_oracle`.
2. Call `getOracleAddress()`; returns `0x000...000`.
3. Submit valid claim signed by real oracle; succeeds.
4. Off-chain system relying on getter has contradictory state.

#### Recommendation
- Implement oracle storage explicitly (e.g., `address public oracle;`) with controlled update function + event emission; or
- Use `AccessControlEnumerable` and return the first oracle role member deterministically.
- Remove misleading comment that says off-chain indexing overrides the getter.

---

### Finding 2: Oracle rotation/event surface is incomplete and inconsistent with interface
**Severity:** Medium  
**Affected Contracts:** `Smart Contracts/contracts/interfaces/IAnalyticsRewards.sol`, `Smart Contracts/contracts/AnalyticsRewards.sol`  
**Confidence:** High

#### Vulnerability Description
Interface declares `OracleUpdated` event, but implementation has no oracle-rotation function and never emits this event. Combined with role-based signer set, this makes secure key rotation ambiguous and undermines auditability.

#### Impact
- Incident response and key hygiene are weaker.
- Harder forensic attribution of signer changes.

#### Recommendation
Add explicit admin-only rotation methods with event emission (grant new oracle, optionally revoke old oracle atomically), or remove interface event if rotation is intentionally out-of-scope.

---

### Finding 3: Reward amount is oracle-controlled and ignores campaign `rewardAmount` metadata
**Severity:** Medium  
**Affected Contracts:** `Smart Contracts/contracts/AnalyticsRewards.sol` (`claimReward`)  
**Confidence:** High

#### Vulnerability Description
`claimReward` validates only budget/nonce/expiry/signature; it does not enforce `amount == campaign.rewardAmount` nor any bounded relation. Oracle can authorize arbitrary per-claim amounts up to remaining campaign budget.

This may be intentional, but it is an undocumented security-critical assumption about oracle honesty and backend correctness.

#### Impact
- Misconfigured/compromised oracle can rapidly deplete campaign budget.
- Economic invariants depend entirely on off-chain controls.

#### Recommendation
If fixed rewards are intended, enforce exact match; if variable rewards are intended, add explicit min/max bounds per campaign and document policy.

## 7) Invariant Violations / Checks
### Checked invariants
- `campaign.spent <= campaign.totalBudget` enforced by remaining-budget check.
- Nonce single-use global invariant enforced by `usedNonces`.
- CEI pattern used before token transfer in `claimReward`.

### Violations/weaknesses
- **State introspection invariant violated**: “oracle returned by getter reflects active signer set” is false.
- **Policy invariant implicit**: “claim amount follows campaign reward policy” is not enforced on-chain.

## 8) Economic Risk Analysis
- Primary economic attack path is **oracle compromise or backend signing bug**.
- Flash loan vectors are low because reward payout does not depend on AMM price/oracle price feeds.
- Budget depletion griefing possible only with valid oracle signatures.

## 9) Upgradeability Risk Analysis
- Contracts are **not proxy-upgradeable** in current form.
- No initializer/storage collision issues observed.
- Governance upgrade risk shifts to redeploy/migration operational risk instead of proxy hijack risk.

## 10) Test Coverage Gaps
Current repository lacks adversarial smart-contract tests for:
- Invalid/malleable signature edge cases (`v`, `s`, short sig).
- Replay attempts across users/chains/contracts.
- Emergency withdraw race conditions around pause.
- Non-standard ERC20 behavior (fee-on-transfer/rebasing/false returns).
- Multi-oracle role membership and signer-discovery consistency.
- Getter correctness (`getOracleAddress`).

## 11) Hardening Recommendations
1. Implement canonical oracle getter and rotation flow with emitted events.
2. Add explicit on-chain reward policy checks (exact or bounded).
3. Add immutable/domain-separated typed data (EIP-712) instead of EIP-191 for clearer signing UX and reduced integration errors.
4. Add operational guardrails: timelocked emergency withdraw and/or circuit-breaker thresholds.
5. Expand test suite with adversarial and invariant tests.

## 12) Final Risk Assessment
- **Overall risk:** **Medium** (centralized trust with one High issue and two Medium issues).
- If privileged keys are uncompromised and operational tooling does not rely on `getOracleAddress`, direct exploitability is moderate.
- Residual risk remains concentrated in admin/oracle key security, off-chain signing correctness, and emergency process integrity.

---

## Automated Security Review Execution Notes
Attempted tools per requested methodology:
- Slither: unavailable in environment.
- Foundry fuzzing: `forge` unavailable in environment.
- Echidna: unavailable in environment.
- Hardhat tests/compile pipeline: blocked by compiler download failure through proxy (HTTP 403 tunnel).

Manual review was therefore primary; findings were validated via code-path analysis.
