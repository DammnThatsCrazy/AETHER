# Audit Finding — <short title>

> One finding per file/issue. Copy this template for each finding.

- **ID:** AETH-<NNN>
- **Severity:** Critical | High | Medium | Low | Informational
- **Likelihood:** High | Medium | Low
- **Impact:** High | Medium | Low
- **Status:** Open | Acknowledged | Fixed | Won't-fix | Disputed
- **Component:** `contracts/AnalyticsRewards.sol` | `contracts/RewardRegistry.sol` | deploy tooling | other
- **Commit:** `<git-sha reviewed>`

## Summary

<1–3 sentence description of the issue.>

## Location

- File: `<path>`
- Function / lines: `<function>()` L`<start>`–L`<end>`

## Description

<Detailed explanation: what the code does, why it is a problem, and the
conditions/preconditions required to trigger it.>

## Impact

<What an attacker gains or what breaks. Tie to an asset in THREAT_MODEL.md and/or a
violated invariant in INVARIANTS.md, e.g. "violates I1 budget non-overspend".>

## Proof of concept

```solidity
// or JS/Foundry test that demonstrates the issue
```

## Recommendation

<Concrete fix. If multiple options, list trade-offs.>

## Aether response

<Filled in by the Aether team: accepted/fixed/mitigated, commit of the fix, or
rationale for won't-fix.>

---

### Severity rubric (for consistency)

| Severity | Guidance |
|----------|----------|
| Critical | Direct, likely loss of funds or permanent lock of significant funds; trivially triggerable. |
| High | Loss/lock of funds under realistic conditions, or complete bypass of a core control (signature/replay/budget). |
| Medium | Limited fund risk, or a control weakened under specific conditions; DoS of a key path. |
| Low | Minor/limited-impact issue; hard-to-trigger edge case. |
| Informational | Style, gas, documentation, or defense-in-depth suggestions. |
