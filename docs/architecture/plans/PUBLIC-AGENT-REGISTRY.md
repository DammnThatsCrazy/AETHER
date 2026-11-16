---
title: Public Agent Registry — Zero-Install Agent, Principal and Relationship Resolution
slug: plans/public-agent-registry
section: architecture
visibility: I
audience: [architect, dev-senior, buyer, exec]
status: experimental
since_version: 0.1.0
related: [architecture/agent-detection-reliability]
canonical_owner: platform@aether
---

# Public Agent Registry

**Status: proposal.** Nothing on this page is implemented. The draft contract in
§6 is a design artifact; it is deliberately not yet in
`packages/shared/contracts/`, so it does not enter the generator pipeline until
the design is accepted.

## 1. Problem

How far can Aether resolve agents, their principals, and the relationships
between them **without** a customer installing an SDK, CLI, webhook or data
connector?

Without an install, Aether cannot see activity inside a customer's product.
What remains is:

1. what happens on **surfaces Aether operates**, and
2. what actors **publish about themselves**: declarations, keys, registry
   entries, ledger transactions, public footprints.

So zero-install mode resolves identity, declarations, credentials and public
traces — not product activity — and every result carries a lower ceiling on how
strong a claim it supports. This is the *zero-install tier* of Agent 360; any
later install upgrades the same records rather than replacing them.

For how reliably the installed paths work today, see
[Agent Detection Reliability](../AGENT-DETECTION-RELIABILITY.md).

## 2. Evidence sources

| # | Source | What it yields | Ceiling (`principalEvidenceClasses`) |
|---|---|---|---|
| S1 | **Aether-operated surfaces**: hosted MCP server, A2A endpoint, verified links, hosted checkout / x402 paywall, hosted consent page | Full activity for whatever comes to Aether | `VERIFIED_AUTHORITY` |
| S2 | **Aether as agent credential issuer**: agent ids, signed delegation grants, grant status checks by relying parties | Credential holders, delegations, validity windows, who checks a credential and when | `VERIFIED_AUTHORITY` |
| S3 | **Agent self-declarations**: A2A Agent Cards (`/.well-known/agent-card.json`, optionally JWS-signed), MCP registries, providers' published crawler user-agents and IP ranges, Web Bot Auth key directories | Agent existence, provider, capabilities, endpoints, verification keys | `PROVIDER_ASSERTED`; `CRYPTOGRAPHICALLY_ATTESTED` when signed |
| S4 | **Public ledgers**: x402 settlements, smart-account session keys and delegations, on-chain agent registries (e.g. ERC-8004) | Wallet activity, wallet-to-wallet delegation with scope and expiry, timestamps | `CRYPTOGRAPHICALLY_ATTESTED` — **for the wallet, not the agent** |
| S5 | **Public footprints**: code-host bot accounts, app installations, `Co-Authored-By` trailers; "automated by" account labels on social platforms; agent marketplaces; certificate-transparency entries for agent endpoints | Agent ↔ owner and agent ↔ provider links, timestamped actions | `PROVIDER_ASSERTED` (platform label) / `TENANT_DECLARED`-equivalent (self-declared) |
| S6 | **Correlation**: shared infrastructure, timing, naming | Candidate relationships only | `INFRASTRUCTURE_CORRELATED` / `TEMPORALLY_CORRELATED` — never promoted alone |

S1 and S2 are the strategic core. If Aether is where agents get credentials and
where humans grant delegation, the relationship is recorded when it is created,
wherever the agent goes afterwards, with nothing installed on any customer
property.

## 3. Invariants

1. **Vantage ceilings are enforced, not advised.** Evidence collected
   outside-in can never reach `server_observed` for a customer property and can
   never assert human presence. The resolver rejects a record whose evidence
   class exceeds its vantage ceiling.
2. **Wallet ≠ agent ≠ person.** A wallet resolves to `actor_kind: unknown`
   until a declaration (S3/S5) or an Aether-issued credential (S2) binds it.
3. **A private person is linked only by their own claim.** Agents and
   organisations may be resolved from public data. A wallet, account or key is
   linked to an individual only when that individual claims it on an
   Aether-operated surface (passkey or wallet signature). Correlation is never
   used to de-anonymise a person.
4. **No agent signal ≠ human.** Absence of agent evidence stays `unresolved`.
5. **Collection respects publisher policy.** `robots.txt`, platform terms and
   rate limits are honoured; every fact keeps its source and fetch time.
6. **Records are upgradeable.** A later SDK, webhook or MCP integration attaches
   stronger evidence to the same record; nothing is re-keyed.

## 4. Worked example

```
shopbot.ai/.well-known/agent-card.json   JWS-signed, provider = ShopCo
    → agent ShopBot, provider ShopCo                   CRYPTOGRAPHICALLY_ATTESTED
Web Bot Auth key directory on shopbot.ai
    → its web requests are verifiable by any site      CRYPTOGRAPHICALLY_ATTESTED
on-chain agent registry entry names wallet 0xA1
    → agent ↔ wallet                                   PROVIDER_ASSERTED (self)
0xA1 settles x402 payments to merchants M1, M2
    → economic activity with timestamps                attested for the wallet only
0xA1 holds a session key from wallet 0xD4 ($500 cap, expires Friday)
    → delegation with scope and validity               CRYPTOGRAPHICALLY_ATTESTED
0xD4's holder signs a passkey confirmation on Aether's consent page
    → human principal, present and approving           VERIFIED_AUTHORITY (opt-in)
```

Without the last step the principal stays `wallet 0xD4, actor_kind: unknown`.

## 5. What it can and cannot answer

| Question | Zero-install answer |
|---|---|
| Which agents exist and who provides them? | Good, for agents that declare or sign themselves |
| Which agents are hiding? | Not answerable |
| Who delegated to whom, with what scope and when? | Strong where signed (S2, S4); medium where declared (S3, S5) |
| Who drove which action, when? | On ledgers and code history, yes; for web sessions on a customer property, no |
| Is a human involved? | Only via declared ownership or the human's opt-in on an Aether surface |
| Which product decision led to a payment? | Not answerable without an install |

## 6. Draft contract

Proposed `packages/shared/contracts/public-agent-registry.json` (not yet added).
It reuses the existing `agent-lineage` vocabularies rather than defining new
evidence classes.

```json
{
  "$id": "public-agent-registry.json",
  "contractVersion": "0-draft",
  "reuses": {
    "principalEvidenceClasses": "packages/shared/agent-lineage.ts#principalEvidenceClasses",
    "lineageRelationshipTypes": "packages/shared/agent-lineage.ts#lineageRelationshipTypes",
    "completenessStates": "packages/shared/agent-lineage.ts#completenessStates"
  },
  "vantages": {
    "aether_operated":   { "ceiling": "VERIFIED_AUTHORITY",        "mayAssertHumanPresence": true  },
    "aether_issued":     { "ceiling": "VERIFIED_AUTHORITY",        "mayAssertHumanPresence": false },
    "self_declared":     { "ceiling": "PROVIDER_ASSERTED",         "mayAssertHumanPresence": false },
    "signed_declaration":{ "ceiling": "CRYPTOGRAPHICALLY_ATTESTED","mayAssertHumanPresence": false },
    "public_ledger":     { "ceiling": "CRYPTOGRAPHICALLY_ATTESTED","mayAssertHumanPresence": false },
    "public_footprint":  { "ceiling": "PROVIDER_ASSERTED",         "mayAssertHumanPresence": false },
    "correlation":       { "ceiling": "INFRASTRUCTURE_CORRELATED", "mayAssertHumanPresence": false }
  },
  "actorKinds": ["agent", "service", "automation", "crawler", "contract", "wallet", "organization", "human", "unknown"],
  "sourceKinds": [
    "a2a_agent_card", "mcp_registry_entry", "provider_crawler_manifest",
    "web_bot_auth_key_directory", "onchain_agent_registry", "onchain_delegation",
    "x402_settlement", "code_host_footprint", "social_automation_label",
    "agent_marketplace_listing", "ct_log_entry", "aether_credential", "aether_consent"
  ],
  "records": {
    "PublicActorRecord": {
      "required": ["public_actor_id", "actor_kind", "completeness", "evidence"],
      "properties": {
        "public_actor_id": "string — stable Aether id (pa_…)",
        "actor_kind": "enum actorKinds",
        "display_name": "string?",
        "provider_ref": "public_actor_id? — the providing organization",
        "endpoints": "string[] — origin-only URLs",
        "verification_keys": "{ kid, alg, source_kind, fetched_at }[]",
        "wallets": "{ chain, address, binding_evidence_ref }[]",
        "completeness": "enum completenessStates",
        "evidence": "PublicEvidence[] (min 1)",
        "claimed_by_subject": "boolean — true only after an opt-in claim (invariant 3)"
      }
    },
    "PublicEvidence": {
      "required": ["evidence_id", "source_kind", "vantage", "evidence_class", "source_url_origin", "fetched_at"],
      "properties": {
        "evidence_id": "string",
        "source_kind": "enum sourceKinds",
        "vantage": "enum keys(vantages)",
        "evidence_class": "enum principalEvidenceClasses — must not exceed vantages[vantage].ceiling",
        "source_url_origin": "string — origin only, never full URL with query",
        "content_hash": "sha256 of the fetched artifact",
        "signature": "{ alg, kid, verified: boolean }?",
        "fetched_at": "RFC 3339",
        "policy": "{ robots_allowed: boolean, terms_basis: string }"
      }
    },
    "PublicRelationship": {
      "required": ["subject_id", "predicate", "object_id", "evidence_class", "evidence_refs"],
      "properties": {
        "subject_id": "public_actor_id",
        "predicate": "enum lineageRelationshipTypes ∪ { PROVIDED_BY, CONTROLS_WALLET, DELEGATED_TO }",
        "object_id": "public_actor_id",
        "evidence_class": "enum principalEvidenceClasses",
        "scope": "string?",
        "valid_from": "RFC 3339?",
        "valid_until": "RFC 3339?",
        "status": "candidate | resolved | conflicting | revoked",
        "evidence_refs": "evidence_id[] (min 1)"
      }
    }
  },
  "rules": [
    "evidence_class <= vantages[vantage].ceiling, else reject",
    "relationship evidence_class = min over its evidence_refs",
    "correlation-only relationships stay status=candidate",
    "actor_kind=human requires claimed_by_subject=true",
    "wallet actor_kind stays unknown/wallet until a binding evidence exists"
  ]
}
```

## 7. Product surface

A customer enters a domain, wallet or agent name and sees the agents that
declare themselves there, their providers, verified keys, on-chain spending and
delegations, and known principals — each fact tagged with its evidence class
and source. That is the zero-install Agent 360. Installing an SDK, webhook or
MCP integration upgrades it to activity-level evidence and agency attribution.

## 8. Phases

| Phase | Scope | Exit evidence |
|---|---|---|
| P0 | Accept this design; move §6 into `packages/shared/contracts/` with generator, parity tests and ownership-map entries | Contract generates; vantage-ceiling rule has unit tests |
| P1 | S3 collectors: A2A Agent Cards, provider crawler manifests + IP ranges, Web Bot Auth key directories | Signed-card verification tests; robots/terms enforcement tests |
| P2 | S2 issuance: Aether agent credentials and signed delegation grants, reusing the lineage `AuthorityRecord` | Grant issue / verify / revoke round-trip |
| P3 | S4 ledgers: x402 settlements, smart-account delegations, on-chain agent registries | Wallet-not-agent invariant tests |
| P4 | S5 footprints and the zero-install Agent 360 view | Invariant-3 (no de-anonymisation) tests; data-rights review |

Data-rights enforcement (`packages/shared/data-rights.ts`) and a privacy review
gate P3 and P4.
