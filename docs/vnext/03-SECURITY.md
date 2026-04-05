# 03 — Security Architecture

Iron-clad defense-in-depth, tailored to AETHER's specific threat surface: ML extraction, data poisoning, supply chain, prompt injection, reviewer collusion, key compromise, federation attacks.

---

## Threat Model (STRIDE + MITRE ATLAS tailored)

### Crown jewels

| Asset | Where | Loss impact |
|---|---|---|
| Trained model artifacts (9 + FM) | MLflow, SageMaker, edge TF.js | IP theft, attestation forgery |
| Identity cluster graph | Neptune, Gold | Deanonymization, sybil empire |
| Trust + attestation signing keys | HSM / KMS | Entire moat collapses |
| Witness-signing SDK root keys | Device KeyStore | Spoofed events, poisoned training |
| Behavioral event streams | Bronze/Silver | PII leak, membership inference |
| Reviewer approval history | Gold, ReviewBatch | DPO policy corruption |
| PSI intersection tables | Federation service | Cross-tenant disclosure |
| A2A hire graph | Neptune | Reputation gaming, collusion seeding |

### Attack classes

| Class | MITRE ATLAS | AETHER surface |
|---|---|---|
| Model extraction / distillation | AML.T0024 | Intelligence API, edge models, attestation queries |
| Training-data poisoning | AML.T0020 | SDK ingestion, reviewer approvals, federation |
| Backdoor / Trojan | AML.T0018 | Third-party pretrained weights |
| Membership inference | AML.T0025 | Profile API, embedding endpoints |
| Model inversion (PII) | AML.T0048 | GNN identity embeddings, contrastive fingerprints |
| Adversarial examples | AML.T0043 | Fraud, bot detection, bytecode prover |
| Prompt injection | AML.T0051 | KIRA planning, BOLT briefings |
| Graph injection | (new) | Lake mutations, Discovery controller, merges |
| Supply chain | AML.T0010 | PyPI deps, SDK builds, Docker, MLflow |
| Side-channel | AML.T0035 | Identity resolution, PSI timing |
| Reward hacking | (RL) | DPO policy, LOOP budget, band tuning |
| Replay / key compromise | STRIDE-T | x402, witness sigs, ZK attestations |
| Reviewer collusion | (insider) | StagedMutation approval chain |

---

## Defense-in-depth: 7 tiers

| Tier | Purpose | Primary controls |
|---|---|---|
| T1 Perimeter | Keep malformed/unauth traffic out | WAF, mTLS, API keys scoped per tenant, rate limits per-principal |
| T2 Authentication + Provenance | Prove who sent the data | Device-bound keypairs, witness signatures, JWT short TTL |
| T3 Data Integrity | Detect tampering + poisoning | Bitemporal schema, hash chains, lineage tracking, ingest anomaly detection |
| T4 Model Boundary | Protect inference + training | Extraction defense mesh, conformal abstention, DP noise, query budgets |
| T5 Graph Integrity | Prevent graph poisoning | StagedMutation workflow, evidence sufficiency, spectral monitoring |
| T6 Agent Safety | Prevent runaway agents | Authority bands, budget ceilings, approval gates, kill switches |
| T7 Cryptographic Root | Protect keys, attestations | HSM/KMS, key rotation, threshold signing, ZK circuit auditing |

---

## Controls per threat class (concrete)

### Model extraction / distillation

| Control | Ship |
|---|---|
| Per-principal query budgets (not per-IP) | Day 1 |
| Watermark + canary outputs (extend existing mesh to all models + FM) | Day 1 |
| Output perturbation with calibrated noise | Day 1 |
| Top-k label-only APIs on edge endpoints | Day 1 |
| Conformal abstention (refuse on OOD) | Day 1 |
| Per-tenant DP epsilon accounting | Phase 2 |
| Query fingerprinting (detect scraping patterns) | Day 1 |
| Decoy models (honeypot endpoints) | Phase 2 |
| FM exposes only downstream task scores, never raw embeddings | Phase 3 |

### Training data poisoning

| Control | Ship |
|---|---|
| Witness signatures weight events (signed=1.0, unsigned=0.5) | Day 1 |
| Quarantine tier for anomalous ingest | Day 1 |
| Data lineage w/ hash chains | Day 1 |
| Robust aggregation (trimmed mean, median) | Phase 2 |
| Influence functions for anomalous examples | Phase 2 |
| Adversarial training (PGD) for fraud/bot/anomaly | Phase 2 |
| DPO dataset curation + reviewer-ID diversity | Phase 2 |
| Label audit (1% manual review weekly) | Phase 2 |

### Backdoors / Trojans

| Control | Ship |
|---|---|
| Neural Cleanse + STRIP scan on every retrain | Phase 2 |
| SBOM for all models (training data hash, code hash) | Day 1 |
| Signed MLflow artifacts | Day 1 |
| Reproducible training (deterministic seeds, pinned snapshots) | Day 1 |
| Ban unvetted HuggingFace pulls; internal mirror allowlist | Day 1 |

### Membership inference / model inversion

| Control | Ship |
|---|---|
| DP-SGD for identity GAT + FM pretrain | Phase 2 |
| Noise floor on embedding API | Day 1 |
| No raw embeddings externally (similarity queries only, top-k) | Day 1 |
| k-anonymity floor on population API (k ≥ 5) | Day 1 |
| Reject differencing-attack query patterns | Day 1 |
| Output rounding/bucketing for LTV, churn, trust | Day 1 |

### Prompt injection

| Control | Ship |
|---|---|
| Strict separation of system prompts from graph-data content | Day 1 |
| Structured-output contracts (JSON schema validation) | Day 1 |
| No direct write access — all writes via StagedMutation | Day 1 (existing) |
| Content from untrusted sources rendered as data, not instructions | Day 1 |
| Canary tokens in system prompts | Day 1 |
| Output must re-reference original objective ID | Day 1 |
| Budget ceiling + step-count cap per Objective | Day 1 (existing) |

### Graph poisoning

| Control | Ship |
|---|---|
| Evidence sufficiency scoring before mutation (conformal) | Day 1 |
| Spectral Laplacian drift monitoring per IdentityCluster | Phase 1 |
| All graph writes via deterministic lake-driven mutations | Day 1 (existing) |
| StagedMutation classes 3/4/5 require human approval | Day 1 (existing) |
| Counterfactual simulator previews impact | Phase 1 |
| Graph diff audit log w/ principal + evidence hash | Day 1 |
| Bitemporal replay for forensic reconstruction | Day 1 (schema) |

### Agent rogue / reward hacking

| Control | Ship |
|---|---|
| Authority bands enforced by policy engine (not agent choice) | Day 1 |
| Budget ceilings checked at every LOOP iteration | Day 1 (existing) |
| Kill switch: per-agent / per-controller / global | Day 1 |
| Counterfactual simulator previews delegation | Phase 1 |
| Shadow lake 30-day simulation before prod rollout | Phase 1 |
| DPO reward capped + regularized (anti-Goodhart) | Phase 2 |
| Recommendation / execution / economic trust separated | Phase 2 |
| Agent container isolation | Day 1 |

### Supply chain (SLSA L3 target)

| Control | Ship |
|---|---|
| SBOM (CycloneDX) per build artifact | Day 1 |
| Pinned deps w/ hashes (pip-compile, uv lock) | Day 1 |
| Dependabot + Snyk + Socket scanning | Day 1 |
| Signed Docker images (cosign / Sigstore) | Day 1 |
| Private PyPI mirror w/ allowlist | Phase 1 |
| CI in ephemeral, network-restricted runners | Day 1 |
| SDK builds reproducible + signed | Day 1 |
| OIDC federation (no long-lived CI secrets) | Day 1 |
| MLflow write scoped to CI service account + MFA | Day 1 |

### Cryptographic / key management

| Control | Ship |
|---|---|
| Attestation signing keys in HSM (CloudHSM/equiv) | Phase 1 |
| Threshold signatures for long-lived keys | Phase 3 |
| Key rotation every 90d (service), 7d (signing), 24h (attestation) | Day 1 |
| SDK root-of-trust rotated via signed manifest | Day 1 |
| ZK circuit third-party audit before prod | Phase 3 |
| EIP-712 w/ domain separation + chain-id binding | Phase 2 |
| Replay protection (nonce + expiry) on attestations | Phase 2 |
| On-chain revocation list | Phase 3 |

### Federation (PSI) attacks

| Control | Ship |
|---|---|
| Malicious-security PSI protocol (not semi-honest) | Phase 4 |
| Per-tenant crypto domain separation | Phase 4 |
| DP noise on cross-tenant outputs | Phase 4 |
| Reputation weighting of participating tenants | Phase 4 |
| Byzantine-tolerant aggregation (tolerates 1/3 malicious) | Phase 4 |
| Audit log per cross-tenant query | Phase 4 |

### Web3 / x402 / on-chain

| Control | Ship |
|---|---|
| x402 replay protection (server-side nonce tracking) | Day 1 |
| Per-request economic cap per agent / window | Day 1 |
| Bytecode analysis before protocol interaction | Day 1 (existing) |
| RPC MITM resistance (cert pinning, cross-provider divergence check) | Day 1 |
| Oracle signer separation per chain | Day 1 |
| N-confirmation before graph commit (chain reorg handling) | Day 1 |

---

## Day-1 Security Gates (non-negotiable)

| # | Gate | Why |
|---|---|---|
| 1 | Bitemporal schema committed | Retrofitting later is catastrophic |
| 2 | Witness signature verifier active (grace period) | Foundation for provable trust |
| 3 | HSM/KMS-backed signing for attestations | One key leak = moat collapse |
| 4 | SBOM + signed artifacts + pinned deps | Supply chain has zero margin |
| 5 | Conformal abstention on every ML output | Safety story for agents |
| 6 | DP noise + k-anonymity on population API | GDPR + inversion defense |
| 7 | Graph mutation audit log (principal + evidence hash) | Forensic reconstruction |
| 8 | Structured-output contract for all controllers | Blocks prompt injection |
| 9 | Per-principal query budgets + watermarks | Extraction defense full surface |
| 10 | Kill switches (global / controller / agent) | Last-line defense |
| 11 | Secrets via short-lived token broker | Baseline hygiene |
| 12 | Threat model + IR runbook documented | Enterprise/regulatory gate |

---

## Extraction Defense Mesh — extensions to existing

The existing `security/model_extraction_defense/` mesh is extended:

| Existing | Hardening |
|---|---|
| Watermark canaries | Per-tier + per-API-key canary fingerprints |
| Output perturbation | Tiered Gaussian noise by auth level |
| Pattern detector | + Entropy-of-query-distribution detector |
| Rate limiter | Replace with **adaptive cost-based** (tokens proportional to entropy gain) |
| Actor risk scoring | Expose red/orange/green back into Trust substrate (bidirectional) |
| **NEW** Query fingerprinting | Hash-embed query sequences; detect cloning patterns |
| **NEW** Decoy models | Honeypot endpoints serving plausible-wrong outputs |
| **NEW** Model stealing bounty | Public bug-bounty category; treat as security research |

---

## Organizational controls

| Control | Cadence |
|---|---|
| Red team exercise | Quarterly (extraction, poisoning, prompt injection, supply chain) |
| Pen test by external firm | Annually |
| Bug bounty program | Continuous (HackerOne or equivalent + Immunefi for Web3) |
| SOC 2 Type II | Gating for enterprise GA |
| IR runbook drills | Quarterly (attestation-key compromise, poisoned-retrain rollback) |
| Model card + data card | Per release |
| Privacy impact assessment | Per new pillar rollout |
| ZK circuit audit | Before any on-chain deployment |

---

## Maturity ladder

| Level | Posture | Target |
|---|---|---|
| L0 Hygiene | Secrets hygiene, pinned deps, mTLS, basic rate limits | Pre-launch |
| L1 Hardened | All Day-1 gates passed; signed artifacts; witness sigs active | Day 1 |
| L2 Resilient | DP-SGD training, conformal everywhere, red-team, reviewer anomaly | +Phase 2 |
| L3 Adversarial-aware | Decoy models, ZK key ceremony, Byzantine federation, bounty live | +Phase 3 |
| L4 Oracle-grade | SOC 2 Type II, annual pentest published, ZK audits, formal verification | +Phase 4 |

---

## Three asymmetric risks that matter most

1. **Supply chain** — one compromised dep or weight defeats every other control. SLSA L3 non-negotiable.
2. **Reviewer collusion** — human-in-loop moat collapses if one reviewer is bribed. Two-reviewer rule + anomaly detection + 7-day rollback window.
3. **Witness signatures** — without provable event origin, the causal graph is built on sand. Ship signing infrastructure Day 1.
