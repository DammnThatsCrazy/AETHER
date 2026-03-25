# Aether Privacy Control Matrix

This matrix maps every Aether data object to its complete set of privacy controls, as enforced by the `shared/privacy/` control plane.

---

## Matrix Legend

**Sensitivity Tiers**: PUBLIC (0) | INTERNAL (1) | CONFIDENTIAL (2) | SENSITIVE_PII (3) | FINANCIAL (4) | REGULATED (5) | HIGHLY_SENSITIVE (6)

**Lawful Bases**: consent | contract | legal_obligation | vital_interest | public_task | legitimate_interest

**Roles**: viewer | editor | support | compliance | data_science | admin | auditor

**Deletion Behaviors**: hard_delete | pseudonymize | tombstone | hash_irreversible | key_destroy | edge_sever | retain_aggregate | immutable

**Training Eligibility**: eligible | excluded | consent_required | anonymized_only | aggregate_only

**Retention Classes**: ephemeral (0d) | short (30d) | standard (365d) | extended (1095d) | compliance (2555d) | permanent (-1) | legal_hold (-1)

---

## 1. User Profile Core

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | User profile core (name, display name, date of birth, address, nationality) |
| **Sensitivity Tier** | SENSITIVE_PII |
| **Lawful Basis Options** | consent, contract |
| **Access Rules** | Min role: compliance. Support role permitted for active support cases with purpose = `support`. Editor role receives MASKED access (partial name, no DOB/address). Field-level encryption required at rest. |
| **Export Rules** | Exportable with approval. DSAR portability requests return full profile. External API responses return MASKED fields only. Bulk export requires compliance officer sign-off. |
| **Retention Rules** | Extended (1,095 days / 3 years from last activity). Account deletion triggers immediate pseudonymization. Legal hold overrides retention. |
| **Deletion Behavior** | pseudonymize — Name, DOB, address replaced with irreversible tokens. User ID retained as pseudonymous key for aggregate analytics. |
| **Training Eligibility** | consent_required — Only usable for training if explicit ML consent record exists and covers the specific training purpose. |
| **External Visibility** | No. Never exposed in public APIs, webhooks, or partner integrations. |
| **Audit Requirements** | Every read/write logged to immutable audit trail. Access attempts without sufficient role logged as denial events. Consent changes logged with before/after state. |

---

## 2. Email / Phone

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Email address and phone number (stored as salted hash; plaintext held only in encrypted PII vault) |
| **Sensitivity Tier** | SENSITIVE_PII |
| **Lawful Basis Options** | consent, contract |
| **Access Rules** | Min role: compliance for plaintext. Support role receives MASKED access (e.g., `j***@e***.com`, `+1***...89`). Editor role: METADATA_ONLY (field presence, verified status). Hash values accessible to internal services for deduplication. |
| **Export Rules** | Exportable with approval. DSAR access/portability returns plaintext from vault. Partner/external integrations receive hash only, never plaintext. |
| **Retention Rules** | Extended (1,095 days). Hash retained for deduplication after account deletion. Plaintext destroyed on pseudonymization. |
| **Deletion Behavior** | pseudonymize — Plaintext destroyed from vault. Hash retained with tombstone flag preventing reverse lookup. Notification preferences purged. |
| **Training Eligibility** | consent_required — Hash form may be used for anonymized cohort analysis with consent. Plaintext never eligible. |
| **External Visibility** | No. Hash may appear in internal service-to-service calls; plaintext never leaves the PII vault boundary. |
| **Audit Requirements** | Vault access logged with requester identity, purpose, and timestamp. Failed decryption attempts trigger security alert. |

---

## 3. Device Fingerprint

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Device fingerprint (browser fingerprint, device ID, OS/version metadata) |
| **Sensitivity Tier** | CONFIDENTIAL |
| **Lawful Basis Options** | legitimate_interest, consent |
| **Access Rules** | Min role: editor. Viewer role: DENIED. Support role: METADATA_ONLY (device type and OS). Compliance role: FULL access. No field-level encryption; encryption at rest required. |
| **Export Rules** | Exportable with approval. DSAR portability includes device list. External APIs: DENIED. |
| **Retention Rules** | Standard (365 days). Stale fingerprints (no session in 90 days) eligible for early purge. |
| **Deletion Behavior** | hard_delete — Fingerprint records fully removed. Associated session linkages severed. |
| **Training Eligibility** | eligible — Can be used for fraud detection model training without additional consent. |
| **External Visibility** | No. Internal only. |
| **Audit Requirements** | Standard access logging. Bulk reads (>100 fingerprints) trigger alert. |

---

## 4. Wallet Address

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Blockchain wallet address (standalone or linked to identity) |
| **Sensitivity Tier** | CONFIDENTIAL (elevated to REGULATED when linked to a verified identity via KYC) |
| **Lawful Basis Options** | legitimate_interest (standalone); legal_obligation (when identity-linked) |
| **Access Rules** | Standalone: min role editor. Identity-linked: min role compliance. Graph traversal from wallet to identity requires compliance role. Unlinked wallet addresses visible for chain analytics at editor level. |
| **Export Rules** | Standalone: exportable. Identity-linked: not exportable. DSAR portability returns wallet addresses associated with the subject. Partner feeds receive unlinked addresses only. |
| **Retention Rules** | Standalone: permanent (public chain data). Identity-linked: compliance (2,555 days) aligned with KYC retention. |
| **Deletion Behavior** | Standalone: retain (public data, no deletion). Identity-linked: edge_sever — Link between wallet and identity severed; wallet node retained as public chain data. |
| **Training Eligibility** | Standalone: eligible. Identity-linked: excluded. |
| **External Visibility** | Standalone: yes (public chain data). Identity-linked: no. |
| **Audit Requirements** | Identity-linking events logged as compliance actions. All traversals from wallet to identity logged with purpose. |

---

## 5. Session / Behavioral Events

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Session events, page views, click streams, feature usage telemetry |
| **Sensitivity Tier** | INTERNAL |
| **Lawful Basis Options** | legitimate_interest |
| **Access Rules** | Min role: viewer. All authenticated internal roles have FULL access. External API: DENIED. Events are not user-facing. |
| **Export Rules** | Exportable. DSAR portability includes session history if requested. Bulk export available for analytics without approval. |
| **Retention Rules** | Standard (365 days). Raw events expire; aggregated metrics retained as permanent. |
| **Deletion Behavior** | hard_delete — Individual session records removed. Aggregate counters retained (retain_aggregate for derived metrics). |
| **Training Eligibility** | eligible — Freely available for model training, A/B test analysis, and recommendation systems. |
| **External Visibility** | No. Internal operational data only. |
| **Audit Requirements** | Standard logging. No special audit requirements beyond system access logs. |

---

## 6. Graph Edges (Observed)

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Directly observed graph relationships (e.g., user-owns-wallet, user-traded-with, entity-registered-at) |
| **Sensitivity Tier** | CONFIDENTIAL |
| **Lawful Basis Options** | legitimate_interest, contract |
| **Access Rules** | Min role: editor. Graph traversal allowed for editor+. Support role: MASKED (edge type visible, connected node details masked). Compliance role: FULL traversal including metadata. |
| **Export Rules** | Exportable with approval. DSAR portability includes all observed edges for the subject. Partner graph feeds include edges with both endpoints consented. |
| **Retention Rules** | Standard (365 days) for transient edges (session-based). Extended (1,095 days) for persistent edges (ownership, registration). |
| **Deletion Behavior** | edge_sever — Edge removed from graph. Connected nodes retained. Aggregate edge counts updated. |
| **Training Eligibility** | eligible — Observed edges can be used for graph ML, link prediction training, and knowledge graph embedding. |
| **External Visibility** | No. Internal graph only. |
| **Audit Requirements** | Edge creation and deletion logged. Traversal queries logged with depth and path. |

---

## 7. Graph Edges (Inferred)

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | ML-inferred graph relationships (e.g., predicted beneficial ownership, inferred entity overlap, probable funding path) |
| **Sensitivity Tier** | REGULATED |
| **Lawful Basis Options** | legal_obligation, legitimate_interest |
| **Access Rules** | Low confidence (<0.5): compliance role only, no traversal. Medium confidence (0.5-0.8): editor role, traversal with masked metadata. High confidence (>0.8): editor role, full traversal. Regulated edge types (BENEFICIAL_OF, OVERLAPS_WITH, etc.) always require compliance role regardless of confidence. |
| **Export Rules** | Never exportable. Not included in DSAR responses. Not available via any external API or partner feed. Internal compliance dashboards only. |
| **Retention Rules** | Compliance (2,555 days). Re-inference may update or replace edges; historical versions retained for audit. |
| **Deletion Behavior** | tombstone — Inferred edges are tombstoned, not hard-deleted. Tombstone retains edge type and timestamp for compliance audit. Metadata stripped. |
| **Training Eligibility** | excluded — Inferred edges are never used for training to prevent feedback loops and model drift. |
| **External Visibility** | No. Never exposed externally under any circumstances. |
| **Audit Requirements** | Full provenance logging: model version, input features, confidence score, inference timestamp. Every access logged with role and purpose. Confidence changes logged. |

---

## 8. Financial Account Records

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Bank accounts, brokerage accounts, wallet custody accounts, payment method records |
| **Sensitivity Tier** | FINANCIAL |
| **Lawful Basis Options** | contract, legal_obligation |
| **Access Rules** | Min role: compliance. Support role: MASKED (last 4 digits, institution name). Editor role: DENIED. Admin/auditor: FULL. Field-level encryption required. |
| **Export Rules** | Exportable with approval. DSAR portability returns account metadata (institution, type, status) but not full account numbers. Regulatory export (SAR, CTR) handled via compliance purpose. |
| **Retention Rules** | Compliance (2,555 days / ~7 years) aligned with financial record-keeping obligations. |
| **Deletion Behavior** | pseudonymize — Account numbers replaced with irreversible tokens. Institution and account type retained for aggregate analytics. Linked transaction history pseudonymized in parallel. |
| **Training Eligibility** | anonymized_only — Only fully anonymized, aggregated account statistics may be used for training (e.g., account type distributions, average balance ranges). |
| **External Visibility** | No. Never exposed externally. MASKED representation (last 4 digits) available for user-facing confirmation screens only. |
| **Audit Requirements** | All access logged with full attribution. Bulk access triggers immediate alert. Changes to account records require two-party approval and are logged as compliance actions. |

---

## 9. Trade / Order / Execution

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Trade orders, execution records, settlement data, order book interactions |
| **Sensitivity Tier** | FINANCIAL |
| **Lawful Basis Options** | contract, legal_obligation |
| **Access Rules** | Min role: compliance. Support role: MASKED (trade pair, status, timestamp visible; amounts and prices masked). Data science role: aggregate_only (anonymized trade volumes, not individual trades). |
| **Export Rules** | Exportable with approval. DSAR portability includes full trade history for the subject. Regulatory reporting (MiFID II, SAR) via compliance purpose with full access. |
| **Retention Rules** | Compliance (2,555 days). Trade records for regulated instruments may have extended legal holds. |
| **Deletion Behavior** | pseudonymize — Trader identity replaced with token. Trade pair, timestamp, and amounts retained for market integrity and aggregate analytics. |
| **Training Eligibility** | anonymized_only — Anonymized trade flow data eligible for market modeling. Individual trade attribution never eligible. |
| **External Visibility** | No. Aggregate market data (volumes, OHLCV) derived from trades may be public; individual trades are never externally visible. |
| **Audit Requirements** | Full trade lifecycle logging (order placed, matched, executed, settled). Compliance review flag for trades exceeding configurable thresholds. Immutable trade audit trail. |

---

## 10. KYC / KYB Records

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Know Your Customer and Know Your Business verification records (identity documents, verification results, risk assessments) |
| **Sensitivity Tier** | REGULATED |
| **Lawful Basis Options** | legal_obligation |
| **Access Rules** | Min role: compliance. Support role: METADATA_ONLY (verification status, risk tier). Editor role: DENIED. Admin role: FULL for investigation purposes only. Document images stored in encrypted vault with separate access controls. |
| **Export Rules** | Not exportable via standard channels. DSAR access returns verification status and data points collected (not original document images, which are retained under legal obligation). Regulatory export only via compliance purpose. |
| **Retention Rules** | Compliance (2,555 days) from relationship end date (not creation date). Some jurisdictions require longer retention; legal_hold applied as needed. |
| **Deletion Behavior** | tombstone — Verification status and risk decision retained as tombstone. Original documents and biometric data destroyed via key_destroy on the encrypted vault. Personal details pseudonymized. |
| **Training Eligibility** | excluded — KYC/KYB data is never eligible for ML training under any circumstances. |
| **External Visibility** | No. Never exposed externally. Verification status (pass/fail) may be shared with regulated partners under legal obligation. |
| **Audit Requirements** | Every access logged as compliance action. Document image views logged with screenshot/download prevention flags. Annual access review required. Verification decision audit trail is immutable. |

---

## 11. Compliance Actions

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | AML alerts, sanctions screening results, suspicious activity reports, compliance decisions, enforcement actions |
| **Sensitivity Tier** | REGULATED (immutable) |
| **Lawful Basis Options** | legal_obligation |
| **Access Rules** | Min role: compliance. Admin role: FULL. Auditor role: read-only FULL. All other roles: DENIED. Tipping-off controls prevent disclosure to subjects of investigation. |
| **Export Rules** | Not exportable via DSAR (subject access exemption for AML/fraud investigations). Regulatory export to authorities via secure, audited channels only. |
| **Retention Rules** | Compliance (2,555 days) minimum. SAR records may be subject to indefinite legal hold. Retention cannot be shortened by any automated process. |
| **Deletion Behavior** | immutable — Compliance actions are NEVER deleted. Subject identifiers may be pseudonymized after retention period, but the action record, decision, and timestamp are permanent. |
| **Training Eligibility** | excluded — Never eligible for ML training. Risk models are trained on anonymized, aggregate patterns only via separate compliance-approved pipelines. |
| **External Visibility** | No. Existence of compliance actions is itself confidential. External regulatory submissions handled via dedicated secure channels. |
| **Audit Requirements** | Immutable audit trail. Every read logged. Access attempts by non-compliance roles logged as security events. Annual regulatory audit review. Chain-of-custody maintained for all compliance artifacts. |

---

## 12. Beneficial Ownership Inference

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | ML-inferred beneficial ownership relationships, ultimate beneficial owner (UBO) graphs, control chain analysis |
| **Sensitivity Tier** | HIGHLY_SENSITIVE |
| **Lawful Basis Options** | legal_obligation |
| **Access Rules** | Min role: admin. Compliance role: FULL for active investigations only (must declare investigation purpose and case ID). Auditor role: read-only. All other roles: DENIED. No graph traversal through beneficial ownership nodes without admin/compliance role. |
| **Export Rules** | Never exportable. Not included in DSAR responses. Not available via any API. Regulatory disclosure only via formal legal process with compliance officer approval. |
| **Retention Rules** | Compliance (2,555 days). Historical inference versions retained for audit trail. Legal hold applied when related to active investigation. |
| **Deletion Behavior** | hash_irreversible — Inference results replaced with one-way hash. Provenance metadata (model version, timestamp) retained. Input features destroyed. |
| **Training Eligibility** | excluded — Beneficial ownership inferences are never eligible for training. Prevents circular inference and regulatory risk. |
| **External Visibility** | No. Maximum restriction. Never disclosed externally except under court order or formal regulatory demand. |
| **Audit Requirements** | Highest audit tier. Every access generates compliance notification. Quarterly review of all access events by compliance committee. Full provenance chain maintained: input data, model version, confidence score, reviewer decisions. |

---

## 13. ML Model Outputs / Scores

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Risk scores, similarity scores, anomaly detection results, recommendation outputs, feature importance values |
| **Sensitivity Tier** | CONFIDENTIAL |
| **Lawful Basis Options** | legitimate_interest, contract |
| **Access Rules** | Min role: editor. Data science role: FULL access including feature attribution. Support role: MASKED (score value visible, features hidden). Viewer role: DENIED for raw scores; aggregate model performance metrics allowed. |
| **Export Rules** | Exportable with approval. DSAR access includes scores that were used in automated decisions affecting the subject (GDPR Article 22 compliance). Feature importance values included in DSAR to explain decisions. |
| **Retention Rules** | Standard (365 days) for real-time scores. Model version snapshots retained for compliance (2,555 days) to support decision explainability. |
| **Deletion Behavior** | hard_delete — Scores are deleted. Model artifacts (weights, configs) retained separately under model governance. Aggregate model performance metrics retained. |
| **Training Eligibility** | eligible — Model outputs can be used for model monitoring, calibration, and ensemble training. Feature attributions eligible for meta-learning. |
| **External Visibility** | No. Scores never exposed in public APIs. User-facing decisions may reference score-derived outcomes (approve/deny) without revealing raw scores. |
| **Audit Requirements** | Model decision logging for all automated decisions. GDPR Article 22 audit trail for decisions with legal or significant effects. Model versioning and lineage tracked. |

---

## 14. Training Datasets

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Curated datasets for ML model training (feature tables, label sets, validation splits) |
| **Sensitivity Tier** | CONFIDENTIAL (elevated to REGULATED if containing fields from REGULATED sources) |
| **Lawful Basis Options** | legitimate_interest (CONFIDENTIAL); legal_obligation (REGULATED) |
| **Access Rules** | Min role: data_science for CONFIDENTIAL datasets. Min role: compliance for REGULATED datasets. Editor role: METADATA_ONLY (dataset card, schema, row counts). Viewer role: DENIED. |
| **Export Rules** | CONFIDENTIAL datasets: exportable with approval for research collaboration. REGULATED datasets: never exportable. All dataset exports require data governance review. |
| **Retention Rules** | Standard (365 days) for active training sets. Archived datasets: extended (1,095 days). Dataset versions used for production models retained for compliance (2,555 days). |
| **Deletion Behavior** | hard_delete for CONFIDENTIAL datasets. tombstone for REGULATED datasets. Associated model versions flagged when training data is deleted. |
| **Training Eligibility** | eligible (by definition, these are training artifacts). However, datasets derived from REGULATED sources inherit the `excluded` flag and may only be used with compliance approval. |
| **External Visibility** | No. Dataset cards (metadata) may be shared internally. Raw data never externally visible. |
| **Audit Requirements** | Full data lineage: source tables, transformations, filtering criteria, anonymization steps. Dataset access logged. Usage in model training logged with model version linkage. |

---

## 15. Admin Actions / Audit Logs

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | System administration actions, data access audit logs, security events, configuration changes |
| **Sensitivity Tier** | INTERNAL (immutable) |
| **Lawful Basis Options** | legal_obligation, legitimate_interest |
| **Access Rules** | Min role: auditor (read-only). Admin role: read-only (admins cannot modify their own audit records). Compliance role: read-only for investigation. No role can write, update, or delete audit logs; they are append-only. |
| **Export Rules** | Exportable for regulatory audit. Not included in DSAR portability (subject can request access to logs about their own data via DSAR access request). Bulk export requires auditor role. |
| **Retention Rules** | Permanent (-1). Audit logs are never automatically expired. Storage tiering moves old logs to cold storage but never deletes them. |
| **Deletion Behavior** | immutable — Audit logs are NEVER deleted or modified. Subject identifiers within logs may be pseudonymized after the subject's retention period expires, but the log entry itself is permanent. |
| **Training Eligibility** | eligible — Anonymized audit patterns can be used for anomaly detection model training (e.g., unusual access patterns). Individual log entries with user identifiers: excluded. |
| **External Visibility** | No. Internal only. Regulatory auditors granted temporary read access via time-boxed auditor role. |
| **Audit Requirements** | Self-auditing: audit log integrity verified via cryptographic hash chain. Tamper detection alerts on hash mismatch. Annual audit log completeness review. |

---

## 16. API Keys

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | API keys, service tokens, webhook secrets (stored as salted hash only; plaintext shown once at creation) |
| **Sensitivity Tier** | HIGHLY_SENSITIVE (hash only stored) |
| **Lawful Basis Options** | contract |
| **Access Rules** | Min role: admin. Key hash visible to admin only. Plaintext never stored and never retrievable after initial creation. Compliance role: METADATA_ONLY (key ID, creation date, last used, scopes). All other roles: DENIED. |
| **Export Rules** | Never exportable. Not included in DSAR responses. Key metadata (creation date, scopes) may be included in account data exports. |
| **Retention Rules** | Standard (365 days) for active keys. Revoked keys: short (30 days) before hash is purged. Key creation/revocation events retained permanently in audit log. |
| **Deletion Behavior** | hash_irreversible — Key hash is the stored form. On revocation, hash is retained briefly for replay detection, then purged. Key metadata tombstoned. |
| **Training Eligibility** | excluded — API keys and their hashes are never eligible for training under any circumstances. |
| **External Visibility** | No. Key prefix (first 4 characters) may be shown in user dashboards for identification. Full hash never exposed. |
| **Audit Requirements** | Key creation, usage, rotation, and revocation logged as security events. Unusual usage patterns (rate spikes, new IP addresses) trigger real-time alerts. |

---

## 17. Support / CRM Content

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Support tickets, chat transcripts, CRM notes, customer communication history |
| **Sensitivity Tier** | SENSITIVE_PII |
| **Lawful Basis Options** | consent, contract |
| **Access Rules** | Min role: support (for own assigned tickets). Compliance role: FULL access across all tickets. Editor role: DENIED. Data science role: aggregate_only (ticket volume, resolution times). Unassigned ticket content: compliance role only. |
| **Export Rules** | Exportable with approval. DSAR portability includes all support interactions for the subject. Agent internal notes: excluded from DSAR (internal operational data). Bulk export requires compliance approval. |
| **Retention Rules** | Extended (1,095 days) from ticket closure. Active tickets: no expiry until closed. Tickets related to complaints or disputes: legal_hold until resolution. |
| **Deletion Behavior** | pseudonymize — Customer name, contact details, and quoted PII within transcripts replaced with tokens. Ticket metadata (category, resolution, timestamps) retained for operational analytics. |
| **Training Eligibility** | consent_required — Support transcripts may be used for NLP model training (intent classification, routing) only with explicit consent. Agent responses (without customer PII) eligible for internal training. |
| **External Visibility** | No. Customer-facing ticket status visible to the authenticated ticket owner only. |
| **Audit Requirements** | Ticket access logged with agent identity. Escalation events logged. PII exposure in ticket content flagged for redaction review. |

---

## 18. Campaign / Attribution Data

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Marketing campaigns, referral attribution, UTM parameters, conversion funnels, A/B test assignments |
| **Sensitivity Tier** | INTERNAL |
| **Lawful Basis Options** | legitimate_interest |
| **Access Rules** | Min role: viewer. All authenticated internal roles have FULL access. Attribution paths that link to user identity: editor role minimum. Cross-campaign user journey analysis: data_science role. |
| **Export Rules** | Exportable. Aggregate campaign metrics freely exportable. User-level attribution paths: exportable with approval. DSAR portability includes campaign touches for the subject. |
| **Retention Rules** | Standard (365 days). Aggregate campaign performance metrics: permanent. User-level attribution: aligned with session event retention (365 days). |
| **Deletion Behavior** | hard_delete — Individual attribution records removed. Aggregate conversion metrics retained (retain_aggregate). Campaign configuration and creative metadata retained permanently. |
| **Training Eligibility** | eligible — Campaign and attribution data freely available for propensity modeling, LTV prediction, and recommendation training. |
| **External Visibility** | No for user-level data. Aggregate campaign performance may be shared with marketing partners under contract. |
| **Audit Requirements** | Standard logging. No special audit requirements. Consent preference changes affecting marketing tracked in consent history. |

---

## 19. Web3 Protocol / Chain Registry

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Blockchain protocol metadata, smart contract registries, token registries, chain configuration, public network data |
| **Sensitivity Tier** | PUBLIC |
| **Lawful Basis Options** | legitimate_interest |
| **Access Rules** | Min role: viewer. No access restrictions. Available to all authenticated and unauthenticated consumers. Public API endpoints serve this data without authentication. |
| **Export Rules** | Freely exportable. No approval required. Available via public APIs, data feeds, and bulk download. |
| **Retention Rules** | Permanent (-1). Public reference data is never expired. Historical chain data retained for completeness. |
| **Deletion Behavior** | hard_delete — Can be removed if data source is deprecated. In practice, rarely deleted; superseded entries are marked deprecated rather than removed. |
| **Training Eligibility** | eligible — Freely available for all training purposes. No restrictions. |
| **External Visibility** | Yes. Fully public. Served via unauthenticated public APIs. Included in open data feeds. |
| **Audit Requirements** | Minimal. Write access logged (who added/updated registry entries). Read access not individually logged due to volume. |

---

## 20. Cross-Domain Identity Links

| Dimension | Policy |
|-----------|--------|
| **Object/Data Class** | Links connecting identities across domains (e.g., TradFi account linked to DeFi wallet, email linked to on-chain address, cross-platform entity resolution) |
| **Sensitivity Tier** | REGULATED |
| **Lawful Basis Options** | legal_obligation, consent |
| **Access Rules** | Min role: compliance. Admin role: FULL. Auditor role: read-only. Editor role: DENIED. Support role: DENIED. Cross-domain links are the most access-restricted non-HIGHLY_SENSITIVE data type. Graph traversal across domain boundaries requires compliance role and declared investigation/compliance purpose. |
| **Export Rules** | Never exportable. Not included in DSAR portability (individual domain data is exported separately; the link itself is classified as investigative intelligence). DSAR access request returns existence of link (yes/no) but not linked entity details from other domains. |
| **Retention Rules** | Compliance (2,555 days) from link creation. Links that are de-confirmed (verified as incorrect) are tombstoned immediately. Legal hold applied for active investigations. |
| **Deletion Behavior** | tombstone — Link record replaced with tombstone retaining link type and timestamp. Both endpoint identifiers stripped. Aggregate cross-domain statistics retained. |
| **Training Eligibility** | excluded — Cross-domain identity links are never eligible for ML training. Prevents re-identification risk and regulatory exposure. |
| **External Visibility** | No. Never exposed externally under any circumstances. Existence of cross-domain linking capability is itself sensitive and not publicly disclosed. |
| **Audit Requirements** | Highest audit tier (shared with beneficial ownership inferences). Every access logged with full attribution, purpose, and case reference. Link creation requires compliance officer approval and is logged as a compliance action. Quarterly access review by compliance committee. |

---

## Summary Matrix (Quick Reference)

| # | Object | Tier | Retention | Deletion | Training | Exportable | External |
|---|--------|------|-----------|----------|----------|------------|----------|
| 1 | User profile core | SENSITIVE_PII | Extended (1095d) | pseudonymize | consent_required | Yes (approval) | No |
| 2 | Email/phone | SENSITIVE_PII | Extended (1095d) | pseudonymize | consent_required | Yes (approval) | No |
| 3 | Device fingerprint | CONFIDENTIAL | Standard (365d) | hard_delete | eligible | Yes (approval) | No |
| 4 | Wallet address | CONFIDENTIAL/REGULATED | Permanent/Compliance | edge_sever | eligible/excluded | Conditional | Conditional |
| 5 | Session/behavioral | INTERNAL | Standard (365d) | hard_delete | eligible | Yes | No |
| 6 | Graph edges (observed) | CONFIDENTIAL | Standard/Extended | edge_sever | eligible | Yes (approval) | No |
| 7 | Graph edges (inferred) | REGULATED | Compliance (2555d) | tombstone | excluded | Never | No |
| 8 | Financial accounts | FINANCIAL | Compliance (2555d) | pseudonymize | anonymized_only | Yes (approval) | No |
| 9 | Trade/order/execution | FINANCIAL | Compliance (2555d) | pseudonymize | anonymized_only | Yes (approval) | No |
| 10 | KYC/KYB records | REGULATED | Compliance (2555d) | tombstone + key_destroy | excluded | Never | No |
| 11 | Compliance actions | REGULATED (immutable) | Compliance (2555d+) | immutable | excluded | Never | No |
| 12 | Beneficial ownership | HIGHLY_SENSITIVE | Compliance (2555d) | hash_irreversible | excluded | Never | No |
| 13 | ML model outputs | CONFIDENTIAL | Standard (365d) | hard_delete | eligible | Yes (approval) | No |
| 14 | Training datasets | CONFIDENTIAL/REGULATED | Standard/Extended | hard_delete/tombstone | eligible (inherited) | Conditional | No |
| 15 | Admin/audit logs | INTERNAL (immutable) | Permanent | immutable | eligible (anon) | Yes (audit) | No |
| 16 | API keys | HIGHLY_SENSITIVE | Standard (365d) | hash_irreversible | excluded | Never | No |
| 17 | Support/CRM content | SENSITIVE_PII | Extended (1095d) | pseudonymize | consent_required | Yes (approval) | No |
| 18 | Campaign/attribution | INTERNAL | Standard (365d) | hard_delete | eligible | Yes | No |
| 19 | Web3 chain registry | PUBLIC | Permanent | hard_delete | eligible | Yes | Yes |
| 20 | Cross-domain links | REGULATED | Compliance (2555d) | tombstone | excluded | Never | No |
