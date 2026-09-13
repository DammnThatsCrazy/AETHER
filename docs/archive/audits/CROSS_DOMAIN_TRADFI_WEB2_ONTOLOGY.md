---
title: Cross Domain Tradfi Web2 Ontology
slug: archive/audits/cross_domain_tradfi_web2_ontology
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Cross-Domain TradFi/Web2 Ontology

## Entity Model (21 Entity Types)

### Person and Identity Entities

| Entity Type | Description | Key Fields |
|-------------|-------------|------------|
| `person` | Natural person, the root identity anchor | full_name, date_of_birth, nationality, tax_residency, status |
| `profile` | A person's representation within a specific system or context | person_id, source_system, external_id, display_name, metadata |
| `application_identity` | Identity within a Web2 application (CRM contact, support user, billing customer) | person_id, application_id, external_id, role, created_at |
| `social_identity` | Identity on a social platform (Twitter, Discord, Telegram, GitHub) | person_id, platform, handle, verified, follower_count |
| `wallet_owner` | Person or entity that controls a blockchain wallet | entity_id, entity_type, wallet_address, chain, verification_method |

### Ownership and Role Entities

| Entity Type | Description | Key Fields |
|-------------|-------------|------------|
| `account_owner` | Legal owner of a financial account | person_id, account_id, ownership_type, ownership_pct, effective_from |
| `beneficial_owner` | Person who ultimately benefits from an account or entity (may differ from legal owner) | person_id, entity_id, benefit_type, ownership_pct, disclosure_status |
| `authorized_user` | Person authorized to act on an account without being the owner | person_id, account_id, authority_level, granted_by, expiration |
| `operator_admin` | Person who administers a platform, application, or tenant | person_id, tenant_id, role, permissions[], mfa_status |
| `advisor_broker_agent` | Person acting in fiduciary or agency capacity for others | person_id, registration_type, crd_number, firm_id, discretionary, clients[] |
| `omnibus_custodial_holder` | Entity holding assets in an omnibus or custodial structure on behalf of underlying beneficiaries | entity_id, custodian_id, structure_type, sub_account_count, total_aum |

### Legal and Corporate Entities

| Entity Type | Description | Key Fields |
|-------------|-------------|------------|
| `legal_entity` | Any legally recognized entity (corporation, LLC, trust, partnership) | name, lei, jurisdiction, entity_type, formation_date, status |
| `business` | Operating business with commercial activity | legal_entity_id, dba_name, industry, revenue_range, employee_count |
| `household` | Grouping of related persons for aggregate analysis | name, members[], address, formation_reason, aggregate_aum |
| `corporate_parent` | Parent entity in a corporate hierarchy | legal_entity_id, subsidiaries[], consolidation_method, ultimate_parent |
| `corporate_subsidiary` | Subsidiary entity in a corporate hierarchy | legal_entity_id, parent_id, ownership_pct, consolidation_status |

### Institutional and Fund Entities

| Entity Type | Description | Key Fields |
|-------------|-------------|------------|
| `institution` | Financial institution (bank, broker-dealer, custodian, exchange) | legal_entity_id, institution_type, charter_type, regulator, license_numbers[] |
| `fund` | Investment fund or pooled vehicle | legal_entity_id, fund_type, strategy, aum, nav, inception_date, domicile |
| `desk` | Trading desk or business unit within an institution | institution_id, desk_name, asset_class_focus, risk_limits, traders[] |
| `strategy` | Investment or trading strategy | fund_id, strategy_type, benchmark, target_return, risk_budget |
| `issuer` | Entity that issues financial instruments | legal_entity_id, issuer_type, outstanding_instruments[], credit_rating |

---

## Identity Linking Model

### Direct Deterministic Links
High-confidence links based on unique identifiers with exact matching.

| Signal Type | Match Logic | Confidence | Example |
|-------------|------------|------------|---------|
| `email` | Exact match on normalized email | 0.95 | user@example.com links bank profile to brokerage profile |
| `phone` | Exact match on E.164 normalized phone | 0.90 | +1-555-0100 links mobile app to KYC record |
| `ssn_hash` | Exact match on SHA-256 hash of SSN | 0.99 | Hashed SSN links tax record to brokerage account |
| `account_number_hash` | Exact match on SHA-256 hash of account number | 0.98 | Hashed account links bank statement to funding source |
| `wallet_address` | Exact match on checksummed address | 1.00 | 0xabc... links on-chain activity to custody record |

### Inferred Probabilistic Links
Lower-confidence links based on behavioral or environmental signals.

| Signal Type | Match Logic | Base Confidence | Decay |
|-------------|------------|-----------------|-------|
| `device_fingerprint` | Canvas, WebGL, font, plugin hash similarity | 0.70 | Decays 0.05/month without re-observation |
| `session_continuity` | Same session crosses domain boundaries | 0.65 | Expires with session |
| `behavioral_continuity` | Similar interaction patterns across platforms | 0.50 | Decays 0.10/month |
| `domain_app_usage` | Same user accesses related applications | 0.45 | Decays 0.08/month |
| `ip_clustering` | Shared IP address within time window | 0.40 | Decays 0.15/month |

### Confidence Weighting
- All links carry a `confidence` score in the range `[0.0, 1.0]`
- Confidence is computed as: `base_confidence * recency_factor * corroboration_factor`
- `recency_factor`: exponential decay based on time since last observation
- `corroboration_factor`: multiplicative boost when multiple independent signals agree (capped at 1.0)
- Source attribution: every link records `source_provider`, `source_system`, `observed_at`

### Reversibility and Provenance
- All links are stored with full provenance: `created_at`, `created_by`, `evidence[]`
- Every merge operation is reversible via `split` with audit trail
- Evidence chain: each link references the raw signals that produced it
- Deletion propagation: GDPR erasure removes links and underlying evidence

### Cross-Domain Linking
- **bank_account_holder <-> brokerage_owner**: Linked via SSN hash, email, or phone with confidence scoring
- **brokerage_owner <-> wallet_owner**: Linked via funding flow (fiat withdrawal to crypto deposit), email, or KYC match
- **bank_account_holder <-> wallet_owner**: Transitive link with confidence decay: `conf(A->C) = conf(A->B) * conf(B->C) * 0.9`
- All cross-domain links carry a `join_type` field: `deterministic`, `probabilistic`, `transitive`

---

## Business/Application Model

### Entity Types

| Entity Type | Description | Key Fields |
|-------------|-------------|------------|
| `company` | Any company in the system (tenant, partner, target) | name, domain, industry, size, status |
| `application` | Software application or platform | company_id, app_name, app_type, url, sdk_key |
| `website` | Web property with tracking | company_id, domain, tracking_enabled, consent_status |
| `domain` | Internet domain owned by an entity | company_id, domain_name, registrar, expiry, dns_records[] |
| `merchant` | Entity that accepts payments for goods/services | company_id, mcc_code, processing_volume, chargeback_rate |
| `broker` | Registered broker-dealer | institution_id, crd_number, finra_member, clearing_arrangement |
| `bank` | Chartered banking institution | institution_id, charter_type, fdic_insured, routing_number_hash |
| `custodian` | Entity that holds assets on behalf of others | institution_id, custody_type, qualified_custodian, assets_under_custody |
| `payment_processor` | Entity that processes payment transactions | company_id, processor_type, supported_rails[], pci_compliant |
| `transfer_agent` | Entity that maintains shareholder records | company_id, registered_with, issuers_served[] |
| `fund_administrator` | Entity that provides fund accounting and NAV calculation | company_id, funds_administered[], nav_frequency |
| `exchange` | Regulated or unregulated trading venue | institution_id, exchange_type, mic_code, asset_classes[], hours |
| `market_maker` | Entity providing liquidity on a venue | institution_id, venues[], instruments[], obligation_type |
| `issuer` | Entity that creates and offers financial instruments | legal_entity_id, issuer_type, outstanding_instruments[], credit_rating |
| `distributor` | Entity that distributes fund shares or securities | company_id, distribution_channels[], agreements[] |
| `crm_organization` | Organization record in a CRM system (Salesforce, HubSpot) | company_id, crm_source, external_id, lifecycle_stage, owner |
| `service_provider` | Entity providing services (audit, legal, compliance, technology) | company_id, service_type, clients[], certifications[] |

### Relationships
- `company` -> `application`: OPERATES
- `company` -> `website`: OWNS_DOMAIN
- `company` -> `merchant`: OPERATES_AS
- `institution` -> `broker` | `bank` | `custodian` | `exchange`: IS_LICENSED_AS
- `company` -> `crm_organization`: REPRESENTED_IN
- `company` -> `service_provider`: ENGAGED_WITH

---

## Account/Portfolio/Trade Model

### Account Types

| Account Type | Description | Typical Owner | Key Fields |
|-------------|-------------|---------------|------------|
| `brokerage` | Standard securities trading account | person, legal_entity | account_number_hash, margin_enabled, option_level |
| `bank` | Deposit account at a chartered bank | person, legal_entity | account_number_hash, account_subtype (checking/savings/money_market) |
| `custody` | Asset safekeeping account | fund, legal_entity | custodian_id, segregated, reporting_frequency |
| `margin` | Leveraged trading account | person, legal_entity | margin_requirement, maintenance_margin, buying_power |
| `retirement` | Tax-advantaged retirement account | person | plan_type (ira/401k/roth), contribution_limit, rmd_required |
| `trust` | Account held in trust | legal_entity | trustee_id, beneficiaries[], trust_type, revocable |
| `omnibus` | Pooled account holding assets for multiple beneficial owners | institution | sub_account_count, beneficial_owners[], decomposition_method |
| `sub_account` | Logical subdivision of an omnibus or master account | person, legal_entity | parent_account_id, allocation_method, pro_rata_share |

### Account Schema
```
Account {
  id:                 uuid
  account_type:       enum (brokerage | bank | custody | margin | retirement | trust | omnibus | sub_account)
  owner_id:           uuid -> entity
  institution_id:     uuid -> institution
  account_number_hash: string (SHA-256)
  status:             enum (pending | active | restricted | closed)
  opened_at:          timestamp
  closed_at:          timestamp?
  jurisdiction:       string (ISO 3166-1)
  currency:           string (ISO 4217)
  metadata:           jsonb
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

### Position Schema
```
Position {
  id:                 uuid
  account_id:         uuid -> account
  instrument_id:      uuid -> instrument
  quantity:           decimal
  cost_basis:         decimal
  cost_basis_method:  enum (fifo | lifo | specific_lot | average)
  market_value:       decimal
  unrealized_pnl:     decimal
  weight_pct:         decimal
  acquired_at:        timestamp
  lot_id:             uuid?
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

### Order Schema
```
Order {
  id:                 uuid
  account_id:         uuid -> account
  instrument_id:      uuid -> instrument
  side:               enum (buy | sell | sell_short | buy_to_cover)
  order_type:         enum (market | limit | stop | stop_limit | trailing_stop | peg)
  time_in_force:      enum (day | gtc | ioc | fok | gtd)
  quantity:           decimal
  limit_price:        decimal?
  stop_price:         decimal?
  status:             enum (pending | submitted | partial_fill | filled | cancelled | rejected | expired)
  submitted_at:       timestamp
  filled_at:          timestamp?
  cancelled_at:       timestamp?
  source:             enum (manual | algorithmic | advisor | api)
  venue_preference:   uuid? -> venue
  metadata:           jsonb
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

### Execution Schema
```
Execution {
  id:                 uuid
  order_id:           uuid -> order
  fill_price:         decimal
  fill_quantity:      decimal
  venue_id:           uuid -> exchange
  execution_time:     timestamp
  settlement_date:    date
  fees:               decimal
  fee_type:           enum (commission | exchange_fee | regulatory_fee | clearing_fee)
  counterparty_id:    uuid? -> institution
  trade_id:           string (venue-assigned)
  metadata:           jsonb
  observed_at:        timestamp
}
```

### Balance Schema
```
Balance {
  id:                 uuid
  account_id:         uuid -> account
  currency:           string (ISO 4217)
  available:          decimal
  pending:            decimal
  held:               decimal
  total:              decimal  // computed: available + pending + held
  margin_used:        decimal?
  buying_power:       decimal?
  as_of:              timestamp
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

### Cash Movement Schema
```
CashMovement {
  id:                 uuid
  account_id:         uuid -> account
  type:               enum (deposit | withdrawal | transfer | dividend | interest | fee | rebate | margin_call | distribution)
  amount:             decimal
  currency:           string (ISO 4217)
  rail:               enum (ach | wire | card | crypto | internal | check | sepa)
  status:             enum (initiated | pending | completed | failed | reversed)
  counterparty_account_id: uuid? -> account
  reference:          string?
  initiated_at:       timestamp
  completed_at:       timestamp?
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

---

## Instrument/Market Model

### Instrument Types

| Type | Description | Identifiers | Key Fields |
|------|-------------|-------------|------------|
| `stock` | Equity share in a public or private company | CUSIP, ISIN, FIGI, ticker | issuer_id, exchange_id, sector, market_cap, dividend_yield |
| `etf` | Exchange-traded fund | CUSIP, ISIN, FIGI, ticker | issuer_id, underlying_index, expense_ratio, aum, creation_unit_size |
| `option` | Equity or index option contract | OCC symbol, FIGI | underlying_id, strike, expiration, option_type (call/put), style (american/european) |
| `future` | Futures contract | exchange symbol, FIGI | underlying_id, expiration, contract_size, tick_size, settlement_type |
| `bond` | Debt instrument | CUSIP, ISIN, FIGI | issuer_id, coupon_rate, maturity_date, face_value, credit_rating, callable |
| `fund` | Mutual fund or private fund | CUSIP, ISIN, FIGI | fund_id, nav, expense_ratio, minimum_investment, redemption_terms |
| `basket` | Custom basket of instruments | internal_id | components[], weights[], rebalance_frequency |
| `index` | Market or custom index | ticker, FIGI | methodology, components[], provider |
| `tokenized_security` | On-chain representation of a traditional security | contract_address, chain_id | underlying_instrument_id, token_standard, transfer_restrictions[] |
| `structured_product` | Custom payoff structure | ISIN, internal_id | underlying_ids[], payoff_type, barrier_levels[], maturity |
| `rate` | Interest rate or benchmark rate | ticker | rate_type, tenor, currency, fixing_frequency |
| `fx` | Foreign exchange pair | ISO 4217 pair | base_currency, quote_currency, spot, forward_points |
| `commodity` | Physical or financial commodity | exchange symbol | commodity_type, unit, delivery_months[], storage_cost |

### Instrument Schema
```
Instrument {
  id:                 uuid
  instrument_type:    enum (stock | etf | option | future | bond | fund | basket | index | tokenized_security | structured_product | rate | fx | commodity)
  name:               string
  ticker:             string?
  cusip:              string?
  isin:               string?
  figi:               string?
  sedol:              string?
  contract_address:   string?
  chain_id:           integer?
  issuer_id:          uuid? -> issuer
  primary_venue_id:   uuid? -> exchange
  currency:           string (ISO 4217)
  status:             enum (active | suspended | delisted | matured | expired)
  sector:             string?
  asset_class:        string?
  metadata:           jsonb
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

### Instrument Relationships
- `instrument` -> `issuer`: ISSUED_BY
- `instrument` -> `exchange`: TRADED_ON (with listing_date, primary flag)
- `instrument` -> `instrument`: UNDERLIES (for derivatives)
- `instrument` -> `instrument`: COMPONENT_OF (for baskets, indices, ETFs)
- `instrument` -> `account`: HELD_IN (via position)
- `instrument` -> `instrument`: TOKENIZED_AS (links traditional to on-chain wrapper)
- `instrument` -> `entity`: COLLATERALIZED_BY (for secured instruments)

---

## Policy/Compliance Model

### KYC/KYB
```
KycStatus {
  entity_id:          uuid -> entity
  status:             enum (not_started | in_progress | approved | rejected | expired | suspended)
  level:              enum (basic | enhanced | institutional)
  provider:           string
  verification_date:  timestamp
  expiration_date:    timestamp
  documents:          string[] (reference IDs, not content)
  risk_rating:        enum (low | medium | high | prohibited)
  pep_status:         boolean
  sanctions_clear:    boolean
  adverse_media:      boolean
  effective_at:       timestamp
  observed_at:        timestamp
  version:            integer
}
```

### AML/Sanctions Screening
```
ScreeningResult {
  entity_id:          uuid -> entity
  screening_type:     enum (sanctions | pep | adverse_media | watchlist)
  provider:           string
  result:             enum (clear | potential_match | confirmed_match)
  match_details:      jsonb?
  screened_at:        timestamp
  next_screening_at:  timestamp
  case_id:            string?
}
```

### Accreditation and Suitability
```
AccreditationStatus {
  person_id:          uuid -> person
  accreditation_type: enum (accredited_investor | qualified_purchaser | qualified_client | institutional)
  verification_method: enum (income | net_worth | professional | entity_assets)
  verified_at:        timestamp
  expires_at:         timestamp
  documents:          string[]
}

SuitabilityProfile {
  person_id:          uuid -> person
  risk_tolerance:     enum (conservative | moderate | aggressive | speculative)
  investment_horizon: enum (short | medium | long)
  liquidity_needs:    enum (low | medium | high)
  experience_level:   enum (none | limited | moderate | extensive | professional)
  objectives:         string[]
  assessed_at:        timestamp
  advisor_id:         uuid? -> advisor_broker_agent
}
```

### Jurisdiction and Trading Restrictions
```
JurisdictionRestriction {
  entity_id:          uuid -> entity
  jurisdiction:       string (ISO 3166-1)
  restriction_type:   enum (blocked | restricted | requires_approval | reporting_only)
  reason:             string
  effective_from:     timestamp
  effective_until:    timestamp?
}

TradingRestriction {
  account_id:         uuid -> account
  instrument_id:      uuid? -> instrument (null = all instruments)
  restriction_type:   enum (no_buy | no_sell | no_short | reduce_only | close_only | size_limit)
  reason:             enum (compliance | margin | regulatory | internal_policy | sanctions)
  limit_value:        decimal?
  effective_from:     timestamp
  effective_until:    timestamp?
}
```

### Market Abuse and Conflict Detection
```
MarketAbusePattern {
  pattern_type:       enum (wash_trading | spoofing | layering | front_running | insider_trading | market_manipulation | pump_and_dump)
  accounts:           uuid[] -> account
  instruments:        uuid[] -> instrument
  evidence:           jsonb
  severity:           enum (low | medium | high | critical)
  detected_at:        timestamp
  status:             enum (detected | investigating | confirmed | dismissed | reported)
  case_id:            string?
}

ConflictOfInterest {
  entity_id:          uuid -> entity
  conflict_type:      enum (insider | advisor_personal | affiliated_issuer | material_nonpublic)
  related_entity_id:  uuid -> entity
  related_instrument_id: uuid? -> instrument
  restriction:        string
  disclosed:          boolean
  effective_from:     timestamp
  effective_until:    timestamp?
}
```

### Beneficial Ownership Concentration
```
OwnershipConcentration {
  entity_id:          uuid -> entity
  instrument_id:      uuid -> instrument
  ownership_pct:      decimal
  threshold_breach:   boolean
  reporting_required: boolean
  schedule:           enum (13d | 13g | 13f | form_4 | none)
  last_filed:         timestamp?
  calculated_at:      timestamp
}
```

### Omnibus Decomposition
```
OmnibusDecomposition {
  omnibus_account_id: uuid -> account
  beneficial_owner_id: uuid -> entity
  instrument_id:      uuid -> instrument
  allocation_quantity: decimal
  allocation_method:  enum (pro_rata | specific | directed)
  effective_at:       timestamp
  observed_at:        timestamp
}
```

---

## Confidence and Completeness Model

### CompletenessStatus Enum
Aligned with the existing Web3 completeness model for consistency across domains.

```
enum CompletenessStatus {
  RAW_OBSERVED    = "raw_observed"       // Data ingested but not validated
  PARTIALLY_ENRICHED = "partially_enriched"  // Some enrichment applied
  CROSS_REFERENCED = "cross_referenced"   // Validated against secondary source
  HIGH_CONFIDENCE = "high_confidence"     // Multiple sources confirm, all fields populated
}
```

### Confidence Scoring
```
ConfidenceMetadata {
  object_id:          uuid
  object_type:        string
  completeness:       CompletenessStatus
  confidence_score:   decimal [0.0, 1.0]
  field_confidence:   map<string, decimal>  // per-field confidence scores
  sources:            SourceAttribution[]
  last_validated_at:  timestamp
  validation_count:   integer
}

SourceAttribution {
  provider_id:        uuid -> provider_registry
  source_type:        enum (primary | secondary | derived | inferred)
  confidence_weight:  decimal [0.0, 1.0]
  observed_at:        timestamp
  staleness_threshold: duration
}
```

### Source Confidence Inheritance
- Each provider in the provider registry carries a `base_confidence` score
- Data ingested from a provider inherits `min(provider.base_confidence, signal.confidence)`
- Derived data carries `parent_confidence * derivation_factor` where `derivation_factor < 1.0`
- Cross-referenced data gets `min(1.0, source_a.confidence + source_b.confidence * 0.5)`

### Provider Confidence Defaults

| Provider | Type | Base Confidence |
|----------|------|----------------|
| Exchange direct feed | Primary | 0.99 |
| Custodian report | Primary | 0.95 |
| KYC provider | Primary | 0.92 |
| Databento | Primary | 0.95 |
| Massive | Secondary | 0.80 |
| CoinGecko | Secondary | 0.85 |
| User self-reported | Secondary | 0.60 |
| Inferred/derived | Derived | 0.50 |

---

## Point-in-Time Model

### Temporal Dimensions

| Dimension | Description | Use Case |
|-----------|-------------|----------|
| `effective_at` | When the state was true in reality | "This position was opened on 2024-03-15" |
| `observed_at` | When the system learned about this state | "We ingested this position record on 2024-03-16" |
| `as_of` | Query parameter for point-in-time reconstruction | "Show me the portfolio as it was known on 2024-03-16" |
| `version` | Monotonic version counter per object | "This is the 4th update to this position record" |

### Bi-Temporal Schema Pattern
Every mutable entity in the ontology carries the following temporal fields:

```
BiTemporalFields {
  effective_at:       timestamp   // NOT NULL, when the fact became true
  effective_until:    timestamp?  // NULL = currently effective
  observed_at:        timestamp   // NOT NULL, when we recorded it
  superseded_at:      timestamp?  // NULL = current version
  version:            integer     // monotonically increasing per object_id
  previous_version:   integer?    // links to prior version for chain traversal
}
```

### Query Semantics

**Current state** (default):
```
WHERE effective_until IS NULL AND superseded_at IS NULL
```

**Point-in-time (as_of)**:
```
WHERE effective_at <= :as_of
  AND (effective_until IS NULL OR effective_until > :as_of)
  AND observed_at <= :as_of
  AND (superseded_at IS NULL OR superseded_at > :as_of)
```

**Historical reconstruction (effective_at range)**:
```
WHERE effective_at >= :start AND effective_at < :end
  AND superseded_at IS NULL  // only latest observations
ORDER BY effective_at ASC
```

### Version Chain
- Each update creates a new row with `version = previous_version + 1`
- The previous row gets `superseded_at = now()`
- Full history is preserved; no data is overwritten
- Compaction policy: archive versions older than retention period to cold storage

### Temporal Consistency Rules
- `effective_at <= observed_at` (you cannot observe something before it happens)
- `version` is unique per `object_id` and monotonically increasing
- `superseded_at` of version N equals `observed_at` of version N+1
- Backdated corrections: insert with `effective_at` in the past but `observed_at = now()`

---

## Graph Edge Families (Cross-Domain)

### entity_to_account
Edges connecting entities to their financial accounts.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `OWNS_ACCOUNT` | person, legal_entity | account | ownership_pct, ownership_type, effective_from |
| `BENEFICIAL_OWNER_OF` | person | account | benefit_type, ownership_pct, disclosure_status |
| `AUTHORIZED_ON` | person | account | authority_level, granted_by, expiration |
| `CUSTODIES_FOR` | institution | account | custody_agreement, segregated, reporting_frequency |
| `ADMINISTERS` | institution | account | service_type, fee_schedule |

### entity_to_entity
Edges connecting entities to other entities.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `MEMBER_OF_HOUSEHOLD` | person | household | role, joined_at |
| `SUBSIDIARY_OF` | legal_entity | legal_entity | ownership_pct, consolidation_method |
| `ADVISES` | advisor_broker_agent | person | relationship_type, discretionary, effective_from |
| `EMPLOYED_BY` | person | legal_entity | role, department, start_date |
| `CONTROLS` | person | legal_entity | control_type, voting_pct |
| `RELATED_TO` | person | person | relationship_type (spouse/parent/child/sibling) |

### account_to_instrument
Edges connecting accounts to financial instruments.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `HOLDS_POSITION` | account | instrument | quantity, cost_basis, acquired_at, lot_id |
| `PLACED_ORDER` | account | instrument | order_id, side, order_type, status |
| `EXECUTED_TRADE` | account | instrument | execution_id, price, quantity, venue_id |
| `COLLATERAL_POSTED` | account | instrument | collateral_type, haircut_pct, margin_requirement |
| `SHORT_POSITION` | account | instrument | quantity, borrow_rate, locate_id |

### account_to_venue
Edges connecting accounts to trading venues and institutions.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `HELD_AT` | account | institution | account_type, opened_at, status |
| `TRADES_ON` | account | exchange | membership_type, routing_preference |
| `CLEARS_THROUGH` | account | institution | clearing_arrangement, margin_terms |

### entity_to_business
Edges connecting entities to business relationships.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `CUSTOMER_OF` | person, legal_entity | company | customer_since, tier, ltv |
| `VENDOR_TO` | company | company | contract_type, contract_value, renewal_date |
| `PARTNER_WITH` | company | company | partnership_type, revenue_share |
| `REGULATES` | institution | company | regulatory_scope, jurisdiction |

### business_to_product
Edges connecting businesses to their products and services.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `OPERATES_APP` | company | application | launched_at, status, sdk_key |
| `ISSUES_INSTRUMENT` | issuer | instrument | issuance_date, outstanding_amount |
| `PROVIDES_SERVICE` | service_provider | company | service_type, sla, contract_id |
| `DISTRIBUTES` | distributor | fund | distribution_channel, agreement_id |

### funding_flow
Edges tracking the movement of money across accounts and rails.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `FUNDED_BY` | account | account | cash_movement_id, amount, rail, completed_at |
| `WITHDREW_TO` | account | account | cash_movement_id, amount, rail, completed_at |
| `SWEPT_TO` | account | account | sweep_schedule, threshold, amount |
| `TRANSFERRED_BETWEEN` | account | account | transfer_type, amount, initiated_by |
| `FIAT_TO_CRYPTO` | account (bank/brokerage) | account (wallet) | on_ramp, amount_fiat, amount_crypto, rate |
| `CRYPTO_TO_FIAT` | account (wallet) | account (bank/brokerage) | off_ramp, amount_crypto, amount_fiat, rate |

### trade_lifecycle
Edges tracking the full lifecycle of a trade from order to settlement.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `ORDER_PLACED_BY` | order | account | submitted_at, source |
| `ORDER_FOR` | order | instrument | side, quantity, order_type |
| `ORDER_ROUTED_TO` | order | exchange | routed_at, routing_reason |
| `EXECUTION_OF` | execution | order | fill_price, fill_quantity, execution_time |
| `EXECUTED_ON` | execution | exchange | venue_id, trade_id |
| `SETTLES_VIA` | execution | institution | settlement_date, settlement_type |
| `GENERATES_POSITION` | execution | position | quantity_delta, cost_basis_impact |

### compliance_relationship
Edges encoding compliance-relevant relationships.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `KYC_VERIFIED_BY` | entity | institution | kyc_level, verified_at, expiration |
| `SCREENED_AGAINST` | entity | screening_result | screening_type, result, screened_at |
| `RESTRICTED_FROM` | entity, account | instrument, jurisdiction | restriction_type, reason, effective_from |
| `CONFLICT_WITH` | entity | entity, instrument | conflict_type, restriction, disclosed |
| `REPORTS_TO` | institution | institution | regulatory_scope, filing_type, frequency |
| `INSIDER_OF` | person | issuer | insider_type, section_16, reporting_obligation |

### cross_domain_overlap
Edges that bridge Web3, TradFi, and Web2 domains.

| Edge Type | Source | Target | Key Properties |
|-----------|--------|--------|----------------|
| `SAME_ENTITY_AS` | entity (domain A) | entity (domain B) | join_confidence, join_type, evidence[] |
| `FUNDS_FROM_TRADFI` | account (bank/brokerage) | account (wallet) | funding_chain[], total_confidence |
| `TOKENIZED_VERSION_OF` | instrument (on-chain) | instrument (tradfi) | token_standard, wrapper_contract, peg_method |
| `MIRRORS_ACTIVITY` | profile (web2) | profile (web3) | correlation_score, signal_types[], observation_window |
| `SHARED_IDENTITY` | identity_cluster | identity_cluster | linking_signals[], combined_confidence, domain_pair |
| `APPLICATION_OVERLAP` | application_identity | application_identity | apps[], behavioral_similarity, session_overlap |
