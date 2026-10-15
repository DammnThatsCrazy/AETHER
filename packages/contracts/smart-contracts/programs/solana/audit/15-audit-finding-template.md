# 15 — Audit Finding Issue Template

Copy one block per finding. To wire this into GitHub, the team can mirror this
block into `.github/ISSUE_TEMPLATE/audit-finding.md` at the repo root (outside
this program's directory, so it is intentionally not created here).

---

## Finding: <short title>

- **ID:** AETHER-SOL-<NNN>
- **Severity:** Critical / High / Medium / Low / Informational
- **Status:** Open / Acknowledged / Fixed / Won't-fix / Disputed
- **Category:** Access control / Replay / Arithmetic / Custody / Signature verify /
  DoS / Rent / Upgradeability / Documentation / Other
- **Component:** `programs/aether_rewards/src/lib.rs` | `domain/src/lib.rs` |
  scripts | registry | docs
- **Location:** `<file>:<line-range>` (commit `<sha>`)

### Description

<What the issue is.>

### Impact

<What an attacker/operator can achieve. Reference the affected asset/invariant,
e.g. "violates I4 — vault underflow".>

### Preconditions / assumptions

<Roles, state, or configuration required to trigger.>

### Proof of concept

```
<test, transaction, or reasoning that demonstrates the issue>
```

### Recommendation

<Concrete remediation. Prefer additive, security-strengthening changes.>

### Affected invariants / threat-model entries

<e.g. I7, A9 — cross-reference audit/06 and audit/02.>

### Auditor notes / response

<Discussion, author response, fix commit + verification.>

---

## Severity rubric (guidance)

| Severity | Definition |
|---|---|
| Critical | Direct loss of vault funds or full auth bypass with realistic preconditions |
| High | Fund loss / auth bypass under specific but plausible conditions; or oracle-trust break |
| Medium | Griefing, DoS, scalability ceiling, or isolation weakness without direct theft |
| Low | Minor deviation, hardening gap, limited-impact edge case |
| Informational | Style, docs, non-security correctness, defense-in-depth suggestion |

## Triage SLA (target)

- Critical/High: fix + re-review before any testnet promotion; blocks mainnet.
- Medium: fix before mainnet or explicit risk-acceptance with sign-off.
- Low/Info: track; batch into the next hardening pass.
