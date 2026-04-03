# Aether Identity Resolution v8.7.1 — Technical Guide

## Overview

Aether's Identity Resolution system unifies user profiles across devices, browsers, wallets, and sessions into a single **Identity Cluster**. It uses a hybrid approach: **deterministic signals** (exact identifier matches) auto-merge immediately, while **probabilistic signals** (fingerprint similarity, IP clustering, behavioral patterns) flag candidate merges for review.

## Architecture

```
SDK Event (with fingerprint + identifiers)
    |
    v
Ingestion Service
    |-- IP Enrichment (MaxMind GeoLite2)
    |-- Normalize & validate
    |-- Publish SDK_EVENTS_VALIDATED
    |
    v
Resolution Consumer (real-time)
    |
    +-- 1. Extract identifiers from event:
    |      anonymousId, userId, email, phone,
    |      wallets[], fingerprintId, ip_hash
    |
    +-- 2. Upsert graph vertices:
    |      DeviceFingerprint, IPAddress, Location,
    |      Email, Phone, Wallet
    |
    +-- 3. Create/update edges:
    |      HAS_FINGERPRINT, SEEN_FROM_IP,
    |      LOCATED_IN, HAS_EMAIL, HAS_PHONE,
    |      OWNS_WALLET
    |
    +-- 4. Find candidate profiles
    |      (other Users linked to same vertices)
    |
    +-- 5. Run deterministic signals
    |      |
    |      +-- Match found? --> AUTO MERGE
    |      |
    |      +-- No match --> Queue for batch
    |
    v
Batch Resolution Job (hourly)
    |
    +-- Run probabilistic signals on candidates
    +-- Compute weighted composite score
    +-- Apply rules engine:
        |
        +-- >= 0.95 confidence --> auto_merge (if configured)
        +-- >= 0.70 confidence --> flag_for_review
        +-- < 0.70 confidence  --> reject
```

## Identity Graph Schema

### Vertex Types

| Vertex | Description | Key Properties |
|---|---|---|
| `User` | A user profile (anonymous or identified) | `anonymous_id`, `user_id`, `traits`, `tenant_id` |
| `DeviceFingerprint` | Unique browser/device identifier | `fingerprint_id` (SHA-256), `canvas_hash`, `webgl_renderer`, `audio_hash`, `screen_resolution`, `timezone`, `language`, `platform` |
| `IPAddress` | Network endpoint | `ip_hash` (SHA-256), `ip_range`, `asn`, `isp`, `is_vpn`, `is_proxy`, `is_tor` |
| `Location` | Geographic position | `country_code`, `region`, `city`, `latitude`, `longitude`, `timezone` |
| `Email` | Email address (hashed) | `email_hash` (SHA-256), `domain`, `is_disposable` |
| `Phone` | Phone number (hashed) | `phone_hash` (SHA-256 of E.164), `country_code` |
| `Wallet` | Blockchain wallet | `address`, `vm`, `chain_ids[]`, `ens`, `classification` |
| `IdentityCluster` | Merged identity group | `cluster_id`, `canonical_user_id`, `confidence`, `member_count`, `resolution_status` |

### Edge Types

| Edge | Direction | Purpose |
|---|---|---|
| `HAS_FINGERPRINT` | User -> DeviceFingerprint | Device ownership |
| `SEEN_FROM_IP` | User -> IPAddress | Network observation |
| `LOCATED_IN` | User -> Location | Geographic association |
| `HAS_EMAIL` | User -> Email | Email ownership (deterministic) |
| `HAS_PHONE` | User -> Phone | Phone ownership (deterministic) |
| `OWNS_WALLET` | User -> Wallet | Wallet ownership (deterministic) |
| `MEMBER_OF_CLUSTER` | User -> IdentityCluster | Cluster membership |
| `SIMILAR_TO` | User -> User | Probabilistic similarity link |
| `IP_MAPS_TO` | IPAddress -> Location | Geolocation mapping |
| `RESOLVED_AS` | User -> User | Identity merge (audit trail) |

## Resolution Signals

### Deterministic Signals (Auto-Merge)

These produce `confidence = 1.0` and trigger immediate merging:

| Signal | Match Logic | Example |
|---|---|---|
| **UserIdSignal** | Same `userId` across profiles | User logs in on phone and laptop |
| **EmailSignal** | Same normalized email hash | Same email in traits from two browsers |
| **PhoneSignal** | Same E.164 phone hash | Same phone number registered from web and app |
| **WalletAddressSignal** | Same wallet address + VM type | MetaMask connected on Chrome and Firefox |
| **OAuthSignal** | Same OAuth provider + subject | Google login on desktop and mobile |

**Email normalization**: lowercase, trim whitespace, remove dots from Gmail local part (j.doe@gmail.com = jdoe@gmail.com), remove plus aliases (user+tag@domain.com = user@domain.com).

**Phone normalization**: E.164 format (+1234567890), strip spaces/dashes/parens.

### Probabilistic Signals (Scored)

These produce variable confidence (0.0-1.0) and are combined using weighted composite scoring:

| Signal | Weight | Scoring |
|---|---|---|
| **FingerprintSimilarity** | 0.35 | Canvas hash (30%), WebGL (25%), audio (15%), screen (5%), timezone+lang (10%), platform (5%), hardware (5%), fonts (5%) |
| **NetworkGraphProximity** | 0.20 | Jaccard similarity on shared graph neighbors |
| **IPCluster** | 0.15 | Same IP = 0.8, same /24 = 0.4, same ASN = 0.15, VPN discount |
| **BehavioralSimilarity** | 0.15 | Cosine similarity on feature vectors (session timing, page frequency, event mix) |
| **LocationProximity** | 0.15 | Same city = 0.6, same region = 0.3, same country = 0.1 |

**Composite score** = `sum(signal_confidence * weight) / sum(weights)`

## Device Fingerprinting

### Web SDK

The `DeviceFingerprintCollector` in `packages/web/src/core/fingerprint.ts` generates a SHA-256 hash from 17 browser signals:

| Signal | Uniqueness | Collection Method |
|---|---|---|
| Canvas rendering | High | Draw test pattern, hash `toDataURL()` |
| WebGL renderer | High | `WEBGL_debug_renderer_info` extension |
| WebGL vendor | Medium | Same extension |
| Audio context | High | `OfflineAudioContext` oscillator hash |
| Font detection | Medium-High | Canvas width measurement for 24 fonts |
| Screen resolution | Low | `screen.width x screen.height` |
| Color depth | Low | `screen.colorDepth` |
| Timezone | Low | `Intl.DateTimeFormat` |
| Language | Low | `navigator.language` |
| Platform | Low | `navigator.platform` |
| Hardware concurrency | Low-Medium | `navigator.hardwareConcurrency` |
| Device memory | Low-Medium | `navigator.deviceMemory` |
| Touch support | Low | `navigator.maxTouchPoints` |

**Privacy**: Only the composite SHA-256 hash leaves the browser. Raw signals are never transmitted. Fingerprinting is skipped when GDPR mode is active and analytics consent is not granted. Cached in localStorage for 7 days.

### iOS SDK

Fingerprint from: `identifierForVendor`, device model, system version, screen dimensions, scale, locale, timezone, processor count, physical memory. SHA-256 via CryptoKit.

### Android SDK

Fingerprint from: `ANDROID_ID`, `Build.MODEL`, `Build.MANUFACTURER`, OS version, display metrics, locale, timezone, available processors. SHA-256 via `MessageDigest`.

### React Native

Delegates to native module: `NativeModules.AetherNative.getFingerprint()`.

## Decision Thresholds

| Threshold | Default | Action |
|---|---|---|
| Auto-merge | 0.95 | Merge profiles immediately (requires deterministic by default) |
| Review | 0.70 | Flag for admin review |
| Reject | < 0.70 | No merge, record as evaluated |

### Configuration

```json
{
  "auto_merge_threshold": 0.95,
  "review_threshold": 0.70,
  "max_cluster_size": 50,
  "cooldown_hours": 24,
  "require_deterministic_for_auto": true,
  "allow_probabilistic_auto_merge": false
}
```

Update via `PUT /v1/resolution/config`.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/resolution/cluster/{user_id}` | GET | Get the full identity cluster for a user |
| `/v1/resolution/pending` | GET | List pending review decisions |
| `/v1/resolution/pending/{id}/approve` | POST | Admin approves a merge |
| `/v1/resolution/pending/{id}/reject` | POST | Admin rejects a merge |
| `/v1/resolution/audit/{decision_id}` | GET | Get full audit trail for a decision |
| `/v1/resolution/config` | GET | Get current resolution config |
| `/v1/resolution/config` | PUT | Update resolution config |
| `/v1/resolution/batch` | POST | Trigger batch probabilistic matching |

### Example: Get Identity Cluster

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  https://api.aether.io/v1/resolution/cluster/user-123
```

**Response:**
```json
{
  "cluster_id": "clust-abc",
  "canonical_user_id": "user-123",
  "confidence": 1.0,
  "member_count": 3,
  "resolution_status": "auto_merged",
  "members": [
    { "user_id": "user-123", "role": "primary", "joined_at": "2026-01-15T..." },
    { "user_id": "anon-456", "role": "merged", "joined_at": "2026-02-01T..." },
    { "user_id": "anon-789", "role": "merged", "joined_at": "2026-03-01T..." }
  ],
  "linked_devices": [
    { "fingerprint_id": "a1b2c3...", "first_seen": "2026-01-15T...", "observations": 47 },
    { "fingerprint_id": "d4e5f6...", "first_seen": "2026-02-01T...", "observations": 23 }
  ],
  "linked_ips": [
    { "ip_hash": "abc123...", "ip_range": "192.168.1.0/24", "observations": 120 }
  ],
  "linked_wallets": [
    { "address": "0x1234...abcd", "vm": "evm", "ens": "user.eth" },
    { "address": "7nY4...Kx3p", "vm": "svm" }
  ],
  "linked_emails": [
    { "email_hash": "def456...", "domain": "gmail.com" }
  ]
}
```

## Safety Mechanisms

| Mechanism | Description |
|---|---|
| **Max cluster size** | Refuse merge if resulting cluster exceeds 50 profiles (configurable). Prevents cascading merges in NAT/VPN scenarios. |
| **Cooldown** | Don't re-evaluate rejected pairs for 24 hours. |
| **Fraud gate** | If either profile has fraud score > 40, route to manual review regardless of identity confidence. |
| **Undo capability** | `RESOLVED_AS` edges store full signal snapshots. Merges can be reversed by restoring the secondary profile and reassigning graph edges. |
| **Privacy** | All PII (email, phone, IP) stored as SHA-256 hashes only. Raw values never persisted in graph or audit trail. |

## Audit Trail

Every resolution decision is recorded in TimescaleDB with:
- Decision ID, profile pair, action taken
- Composite confidence score
- Whether deterministic match was found
- Full signal snapshot (all signal results at decision time)
- Timestamp and who decided (system or admin)

Query via: `GET /v1/resolution/audit/{decision_id}`

## Event Topics

| Topic | When Emitted |
|---|---|
| `aether.resolution.evaluated` | Every time a candidate pair is evaluated |
| `aether.resolution.auto_merged` | When an auto-merge is executed |
| `aether.resolution.flagged` | When a pair is flagged for review |
| `aether.resolution.approved` | When an admin approves a merge |
| `aether.resolution.rejected` | When an admin rejects a merge |
| `aether.identity.fingerprint.observed` | When a fingerprint vertex is created/updated |
| `aether.identity.ip.observed` | When an IP vertex is created/updated |

## SDK Integration

### Sending Identity Signals

```typescript
// Web SDK — all signals are captured automatically
aether.init({ apiKey: 'your-key' });

// Fingerprint: auto-generated and included in every event context
// IP: captured server-side from request headers
// Location: derived from IP via MaxMind GeoLite2

// To enable cross-device resolution, provide explicit identifiers:
aether.identify('user-123', {
  email: 'user@example.com',     // Deterministic cross-device link
  phone: '+14155551234',          // Deterministic cross-device link
  oauthProvider: 'google',        // OAuth-based linking
  oauthSubject: 'google-uid-xyz', // OAuth subject ID
});

// Wallet connections are automatically tracked:
// When a user connects MetaMask on desktop AND Phantom on mobile,
// the backend resolves both to the same identity cluster.
```

## Agent Identity Resolution

v8.0 extends the identity graph to autonomous AI agents and smart contracts.

**AGENT vertex** — Every registered agent receives its own `AGENT` vertex in the identity graph, connected to its owner via a `LAUNCHED_BY` edge pointing to the owner's `User` vertex. Agent identity links include:
- `owner_user_id` — the human user who deployed or owns the agent
- `model_name` — the underlying model (e.g. `gpt-4o`, `claude-opus-4-20250514`)
- `capabilities[]` — declared capability set (e.g. `['trade', 'analyze', 'deploy']`)
- `wallet` — the agent's on-chain wallet address (if applicable)

**Cross-layer resolution (H2A edges)** — Human-to-Agent (`H2A`) edges trace attribution from agent actions back to the human users who launched them. When an agent performs an on-chain action or records a decision, the resolution consumer follows the `LAUNCHED_BY` edge to attribute the activity to the owning `IdentityCluster`. This enables end-to-end auditability across the human-agent boundary.

**CONTRACT vertex** — Smart contracts deployed by agents receive a `CONTRACT` vertex linked to the deploying agent via a `DEPLOYED` edge (`AGENT → CONTRACT`). Contract vertices store `address`, `chain_id`, `bytecode_hash`, and `deployer_agent_id`, enabling full provenance from contract back to human owner through the agent layer.
