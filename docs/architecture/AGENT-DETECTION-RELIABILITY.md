---
title: Agent Detection Reliability — Assessment and Remediation
slug: architecture/agent-detection-reliability
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: 0.1.0
source_files: [services/api/journeys/traffic/classifier.py, services/api/journeys/traffic/agent_verification.py, services/api/journeys/traffic/web_bot_auth.py, services/api/journeys/traffic/forwarded_evidence.py, services/api/journeys/traffic/protocol_identity.py, packages/sdk/server/src/protocol-identity.ts, packages/sdk/python/aether_agentic/protocol_identity.py, packages/sdk/ios/Sources/AetherSDK/AutomationSignals.swift, packages/sdk/android/src/main/java/com/aether/sdk/AutomationSignals.kt, config/release/feature_flags/staging.yaml, config/release/feature_flags/production.yaml, infra/aws/terraform/modules/ecs/main.tf, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/actions/agent/agent360_provider.py, services/api/ingestion/device_integrity/app_attest.py, services/api/ingestion/device_integrity/play_integrity.py, services/api/ingestion/device_integrity/tokens.py, services/api/ingestion/device_integrity/routes.py, packages/sdk/ios/Sources/AetherSDK/DeviceIntegrity.swift, packages/sdk/android/src/main/java/com/aether/sdk/DeviceIntegrity.kt, packages/sdk/server/src/request-evidence.ts, packages/sdk/python/aether_agentic/request_evidence.py, services/api/journeys/traffic/referral_links.py, services/api/journeys/traffic/metrics.py, services/api/ingestion/ingestion/batch.py, services/api/ingestion/silver/dispatcher.py, services/api/ingestion/silver/projectors/touchpoint_projector.py, services/api/journeys/measurement/engine/attribution_engine.py, services/api/journeys/measurement/engine/journey_compiler.py, services/api/journeys/measurement/silver_adapters.py, packages/sdk/web/src/utils/index.ts, packages/sdk/web/src/types.ts, packages/sdk/server/src/agentic.ts, services/api/actions/agent/attestation.py, services/api/actions/agent_lineage/engine.py, services/api/actions/agent_lineage/evidence.py, services/api/config/settings.py]
related: [operations/agent-layer-production, plans/public-agent-registry]
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
source_hashes:
  "config/release/feature_flags/production.yaml": "sha256:11cfe531416ce07c52f402811e6719d036efcd88a0cab458194c78712855a03d"
  "config/release/feature_flags/staging.yaml": "sha256:7578d37520a983f7c6a5117cfc9e6a624c2e2a533ea0e1346049cf7a189f5056"
  "infra/aws/terraform/modules/ecs/main.tf": "sha256:867cc96ca6b3b0020680e4b9402ed3462a0e4191b61b2fc374d03d44a606fc08"
  "packages/sdk/android/src/main/java/com/aether/sdk/AutomationSignals.kt": "sha256:e4b92160a166df33266838a65d5b2fb54627362f1f408ba0b866696aede9d21e"
  "packages/sdk/android/src/main/java/com/aether/sdk/DeviceIntegrity.kt": "sha256:55abb4473b991539ecc9ab831eb3aff01f61d75753fdcc61239ad53a775acb4a"
  "packages/sdk/ios/Sources/AetherSDK/AutomationSignals.swift": "sha256:3ec9083a9cc6588e755cd53e04f9e6ccc5e3bc2f39a9536c4f36e27c9fb02e58"
  "packages/sdk/ios/Sources/AetherSDK/DeviceIntegrity.swift": "sha256:815b3cf4a60e8001a0d837a5c18c5392001a2770856bb8b625aa100bcd1012ec"
  "packages/sdk/python/aether_agentic/protocol_identity.py": "sha256:a0a54e7ebf79f939042d6caacb7f1043c8de4bf812ba8745cf5f5676f42bbdb0"
  "packages/sdk/python/aether_agentic/request_evidence.py": "sha256:f124aa7b8e78c1284f8a0f0770407a842eabc61459802930038a990ae3ee9989"
  "packages/sdk/server/src/agentic.ts": "sha256:da675cdd08068013c1700c8e65943b55a31950c3399b2efb8b67cb08af4107db"
  "packages/sdk/server/src/protocol-identity.ts": "sha256:894f29a47f0dcb8a482c0f73927bfb0f260668e932124f617fe08944cc1cdadc"
  "packages/sdk/server/src/request-evidence.ts": "sha256:0c6673b18f400d3e73e36d004650d8a915e38652839aab168a638263a20fcdf9"
  "packages/sdk/web/src/types.ts": "sha256:0b12cb075729098df014e453361ce3d42c47b016db643350bc8a44dfd03344a9"
  "packages/sdk/web/src/utils/index.ts": "sha256:69d575c70eba14c95cd7f0b82659bf7db7c8c3151dbb63d05fefcb4b137412ce"
  "services/api/actions/agent/agent360_provider.py": "sha256:4f903310623b89e4616b8f822028fa5a52bda10651b1146267b1c5c77ab7db96"
  "services/api/actions/agent/attestation.py": "sha256:d0930009a39420b36c083d51ba05cbd2261d6a7aa66589c9509fb62707199655"
  "services/api/actions/agent_lineage/engine.py": "sha256:da90a532b17db5e7359823c15ad44b7c45583038c5f40cf8edbcf6eda2fc3f04"
  "services/api/actions/agent_lineage/evidence.py": "sha256:80870d50700b4c9f1e6e04d20da5a49476edf52475a8dee9c1779937ba5738cc"
  "services/api/config/settings.py": "sha256:b1c2ebd96136fe70afcbaf79ebef7ac4076c4727de20cd8fb955fa07c78bf508"
  "services/api/ingestion/device_integrity/app_attest.py": "sha256:c0c8337aa587799fb87ae67cfd942c2c32db4f7fab4e23a4a39684181e8b3a4e"
  "services/api/ingestion/device_integrity/play_integrity.py": "sha256:556236e83bcc2e4db2a43a4116c3b87794ecffb02e24a43592362ebea4c98178"
  "services/api/ingestion/device_integrity/routes.py": "sha256:28f99915d7dc6a7ce96caf318bce4adc682687cc3aafcb26dd245bb95fcf67aa"
  "services/api/ingestion/device_integrity/tokens.py": "sha256:cbe855db578486a6a1c156d5ab8d47a8ebf37b4798dda3f89aae918de6124cd7"
  "services/api/ingestion/ingestion/batch.py": "sha256:edcd2e94c445e083a219d89f7eb484fd67aeb3d01aa055c36e68589c789593b5"
  "services/api/ingestion/silver/dispatcher.py": "sha256:f1ac1e82dd95a777fdc182b5f5c1451548c9cf3208b5bd0651d99f299910a4fb"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:73e568f142ad0407405cd3fff0328011d6e2a58260e48075cb5eedc5f5cd952c"
  "services/api/ingestion/silver/projectors/touchpoint_projector.py": "sha256:3ac990ca4cc58e8f8ad7b5023764b59dd14733e0d6688564408bf13819871d4d"
  "services/api/journeys/measurement/engine/attribution_engine.py": "sha256:a4d7048ab540db38e948daf17c411ec610887107934d42253d0be9a2c7f252c9"
  "services/api/journeys/measurement/engine/journey_compiler.py": "sha256:5cb88fcdb807f9dc52e1cf6e3966d81f6b9f4509a5cdc1517300bed6ce1179df"
  "services/api/journeys/measurement/silver_adapters.py": "sha256:084dfd921dce491ec3eceb43d494a3afbb4e7bfdf580486b21b6c512e2266165"
  "services/api/journeys/traffic/agent_verification.py": "sha256:06839e165b37e38db25690424e427419978585ac4105ff836b6adf2bc0171341"
  "services/api/journeys/traffic/classifier.py": "sha256:c438ff05ee5da57b954ed47c7c7301f6d9aeb24e5e8e3bee1454d57b9cf55199"
  "services/api/journeys/traffic/forwarded_evidence.py": "sha256:cfed0417980530581d6b1c7697e3459b0c3a397775214916ee480cc51ef9758d"
  "services/api/journeys/traffic/metrics.py": "sha256:6f6a97826153619931bf04d7c3c865c2896d976b4cb834c14444989ed4ac1cc4"
  "services/api/journeys/traffic/protocol_identity.py": "sha256:44599b2e75658cda9cedb4f37648a97c01c4a385ca3cb6329690e83db9883920"
  "services/api/journeys/traffic/referral_links.py": "sha256:a50ba8985185c48e664b906c06b7a753457f4daf7731d3cf6c5433f9937bf7c5"
  "services/api/journeys/traffic/web_bot_auth.py": "sha256:adc124afaa9894d0ae67064ab4bd72e1a9a279ba81d5b04a759b7f71e6c3bf20"
---

# Agent Detection Reliability — Assessment and Remediation

**Question:** how reliably does Aether track AI agents through the surfaces
customers install (SDKs, server integrations, webhooks)? A human / agent graph
is only as trustworthy as the weakest path feeding it.

**Target:** every path at **medium** reliability or better, **high** where the
evidence allows. "Reliable" here means two things: what we label, we label
correctly and at the right strength; and what we cannot see, we record as
`unknown` instead of guessing.

**Status:** Phase 1 (§3) and Phase 2 (§4: Web Bot Auth, server-forwarded
request evidence, MCP / A2A identity, mobile automation evidence, and the
deployment registry turned on) are implemented. Every path is at medium or
better where a signal honestly exists; agents that hide (unsigned, no
automation flag) stay `unknown`, never `human`. §6 lists what remains. This page is an
engineering assessment, not a readiness claim; see `scripts/production_status.py`.

## 1. Reliability by path

| Path | Before Phase 1 | Now | Why |
|---|---|---|---|
| Server SDK events, signed (Ed25519) | High, registry off by default | **High**, registry on in staging and production | `attestation.py` verifies signatures; registry enabled in the release flag files (§4.5) |
| Server SDK events, unsigned | Medium | **Medium** | Fields are source-reported; recorded as such |
| Delegation / authority records | High | **High** | Lineage resolver separates verified from declared, owner-only grants |
| Declared AI user-agents (GPTBot, ChatGPT-User, PerplexityBot, …) | Low–medium, overclaimed | **High** where the provider publishes IP ranges; **medium** otherwise | Server checks the real header + client IP against published ranges; unverifiable claims are labelled `declared` |
| Undetected actors (all web / mobile traffic) | Counted as **human** | **Correctly `unknown`**, and measured | No more human default anywhere in the touchpoint, attribution, adapter or journey path |
| Browser automation (WebDriver-driven browsers) | None | **Medium** (inferred) | Web SDK reports `navigator.webdriver`; classified `machine`, never `agent` or `human` |
| Agent in a real browser without WebDriver (CDP, extensions, computer-use) | None | **High** when the agent signs with Web Bot Auth and Aether holds its keys (ChatGPT today); otherwise `unknown` | RFC 9421 signature verified on `/v1/batch` and verified-link redirects (§4.1); unsigned agents have no honest client signal |
| Agent that does not run JavaScript | None | **High** for Web Bot Auth signers and **medium–high** for range-verified agents, when the customer forwards request evidence from the server SDK; invisible on browser-SDK-only sites | `captureRequestEvidence` → verified at ingestion, graded as observed by the tenant's server (§4.2) |
| Mobile apps driven by a test / automation harness | None | **Medium** (inferred) | iOS / Android SDKs report `testHarness` → `machine`; emulator recorded as evidence only (§4.4) |
| Mobile app / device genuineness (App Attest, Play Integrity) | None | **Medium–high** once configured: a failed attestation is automation; a verified one rules out spoofed or scripted clients for that install | Opt-in attestation, server-verified integrity token on every event (§4.7) |
| MCP clients and A2A callers | None | **Medium–high**: `server_observed` when the tenant's server authenticated the client (OAuth / A2A auth), `declared` from clientInfo or an Agent Card alone | Server SDK `captureMcpClientIdentity` / `captureA2aCallerIdentity` (§4.3) |

"Detection reliability" is now itself measured: `actor_detection_total
{actor_type, proof_level, verification_level}` (§3.3). The share labelled
`unknown` is the size of the remaining gap.

## 2. Baseline findings (before Phase 1)

1. **Missing evidence became "human."** `classifier.py` returned
   `explicit_actor_type or "human"` in ten branches; `attribution_engine.py`
   set `human` for any touchpoint with an `anonymous_id` (every web SDK event);
   `silver_adapters.py` hard-coded `human` for touchpoints, web3 transactions,
   identity evidence, outcomes, revenue, exposure, account activity and
   conversions; `journey_compiler.py` defaulted both sides of a transition to
   `human`. Every undetected agent was counted as a person.
2. **User-agent matches overclaimed.** A substring match on a client-supplied
   user-agent was labelled `server_observed` with confidence 0.98 / 0.92, with
   no check against the provider's published IP ranges.
3. **The strong path was off by default and nothing measured reliability.**
4. **No automation evidence** was captured by any SDK.

## 3. Phase 1 — implemented

### 3.1 `unknown` instead of `human`

Actor type is set only from evidence: a declared actor, an `agentId`, a
verified or declared agent user-agent, or the automation flag. Otherwise it is
`unknown`.

- `classifier.py`: all no-evidence branches return `unknown`.
- `attribution_engine.py`: an identity id no longer implies a human.
- `silver_adapters.py`: every adapter uses the row's own `actor_type`, else
  `unknown`.
- `journey_compiler.py`: `unknown → agent` is not a `human_to_agent` handoff.

Effect on attribution: `ActorWeightedModel` weights `unknown` touchpoints at
1.0 (neutral) instead of the human weight (0.7). Journeys and attribution
results computed before this change will differ when recomputed; restatement
follows the existing reclassification path.

### 3.2 Graded verification of declared agents

`journeys/traffic/agent_verification.py` runs during `/v1/batch` ingestion
(`batch._build_agent_verification`). It reads the request's own `User-Agent`
header and the trusted client IP (`context_enricher.resolve_client_ip`, which
ignores forwarded headers from untrusted peers). It checks the IP against the
provider's published ranges in `agent_provider_ranges.json`, and writes only
`{ua_signature, verification}` to `server_context.agent_verification`. The raw
IP is never stored.

| Evidence | `proof_level` | `verification_level` | Confidence |
|---|---|---|---|
| Payload user-agent only | `declared` | `user_agent_claim` | 0.5 |
| Real request header | `declared` | `user_agent_header` | 0.7 |
| Header, IP outside published range | `declared` | `user_agent_ip_mismatch` | 0.3 |
| Header, IP inside published range | `platform_verified` | `provider_ip_range` | 0.95 (agent) / 0.98 (crawler) |

The server-observed header wins over a conflicting payload claim. Ranges are
refreshed with `scripts/refresh_agent_provider_ranges.py` (OpenAI GPTBot,
ChatGPT-User, OAI-SearchBot; PerplexityBot, Perplexity-User). Providers that
publish no machine-readable range list stay `declared`; endpoints are never
guessed.

### 3.3 Reliability metric

`actor_detection_total{actor_type, proof_level, verification_level}` is
emitted for every classified touchpoint (`dispatcher._emit_classification_metrics`,
`journeys/traffic/metrics.py`). All labels are bounded classifier vocabulary.

### 3.4 Browser automation evidence

The web SDK adds `context.device.automation = {webdriver, trustedInputSeen}`
(`packages/sdk/web/src/utils/index.ts`). Both are presence booleans: no
timings, coordinates, key values or movement patterns are read, so nothing
biometric is collected. The projector maps `webdriver: true` to
`actor_type: machine` with evidence `actor:webdriver_flag`. A declared actor or
`agentId` takes precedence. `webdriver: false` and `trustedInputSeen: true` are
**not** treated as evidence of a human: automation can produce trusted events.

## 4. Phase 2 — implemented

### 4.1 Web Bot Auth

Signing agents (draft-meunier-web-bot-auth-architecture) attach an RFC 9421
HTTP Message Signature to their requests, made with an Ed25519 key published at
`<signature-agent>/.well-known/http-message-signatures-directory`. These agents
usually send a normal browser user-agent, so the signature is the only way to
verify them.

- `journeys/traffic/web_bot_auth.py` verifies the signature tagged
  `web-bot-auth`: `@authority` must be covered (and `signature-agent` when that
  header is sent); `created`/`expires` must be current (60 s skew, at most 24 h
  validity); the key must be in the snapshot and belong to the named signer;
  the Ed25519 signature must verify over the RFC 9421 signature base. A repeated
  nonce within one process is flagged as a replay.
- Keys come from `journeys/traffic/web_bot_auth_directories.json`, written by
  `scripts/refresh_web_bot_auth_directories.py` (each key's `kid` is checked
  against its RFC 7638 thumbprint). Nothing is fetched at request time. The
  snapshot holds ChatGPT (`https://chatgpt.com`) today.
- The authority is the request's `Host`, or `X-Forwarded-Host` only from a
  trusted proxy, so a client cannot choose what it is verified against.
- Runs on `/v1/batch` (`batch._build_web_bot_auth` → `server_context.web_bot_auth`)
  and on verified-link redirects (`referral_links._apply_web_bot_auth`).
- Interoperability is tested against signatures produced by Cloudflare's
  reference `web-bot-auth` library (`tests/fixtures/web_bot_auth_reference_vectors.json`).

| Outcome | Classification |
|---|---|
| `web_bot_auth_verified` | Outranks every user-agent claim: `agent` (or `machine` for a crawler signer), `proof_level: platform_verified`, `verification_level: web_bot_auth`, confidence 0.99 |
| `web_bot_auth_unknown_signer` | Well-formed signature, no keys held: self-declared automation (`machine`), unverified, evidence `actor:web_bot_auth_unknown_signer` |
| `web_bot_auth_invalid` / `_expired` / `_replay` | Proves nothing: actor unchanged, kept as evidence `actor:<state>` |

Only the verdict, signer origin and key id are stored; never header values or
signatures.

### 4.2 Server-forwarded request evidence

Agents that never run JavaScript (fetchers, API clients, most crawlers) do not
trigger the browser SDK. The server SDKs capture what the customer's server saw
on the incoming request: `captureRequestEvidence(req)` (Node: `IncomingMessage`
or Fetch `Request`) and `capture_request_evidence(...)` /
`capture_request_evidence_from_wsgi(environ)` (Python). The result travels as
`context.requestEvidence`: user-agent, client IP, method, host, path, query and
the three signature headers; never bodies, cookies or authorization headers.
With `trust_forwarded_for` set behind a proxy the customer controls, the client
IP is the first `X-Forwarded-For` address, falling back to the socket peer
(`REMOTE_ADDR` in WSGI) only when that header is absent.

At ingestion `batch._apply_forwarded_request_evidence` verifies it
(`journeys/traffic/forwarded_evidence.py`), writes verdicts to
`server_context.forwarded_request`, and **always removes the raw evidence**, so
client IPs and signature headers are never stored. A signature's validity is
checked at the forwarded `receivedAt`, which must lie within 24 hours before
ingestion and no more than 60 s after.

The evidence was observed by the tenant's server, not Aether, so it is graded
one step lower, and Aether's own observation of the same request wins:

| Forwarded evidence | `proof_level` | `verification_level` | Confidence |
|---|---|---|---|
| Declared agent UA, IP in provider range | `server_observed` | `provider_ip_range_forwarded` | 0.85 |
| Declared agent UA, no range to check | `declared` | `user_agent_header_forwarded` | 0.65 |
| Declared agent UA, IP outside range | `declared` | `user_agent_ip_mismatch_forwarded` | 0.3 |
| Web Bot Auth signature verified | `platform_verified` | `web_bot_auth_forwarded` | 0.97 |

A signature stays cryptographically verifiable wherever it was observed: it
binds the signer to the customer's host and a short validity window.

### 4.3 MCP and A2A identity

The customer's MCP server or A2A agent knows who is calling it. The server SDKs
forward that as `context.agentProtocol`:

- **MCP** — `captureMcpClientIdentity({ clientInfo, authInfo })` (Node) /
  `capture_mcp_client_identity(...)` (Python): the `initialize` handshake's
  `clientInfo`, and — only when the server's auth middleware verified the bearer
  token (the MCP SDK sets `authInfo` only then) — the OAuth `client_id`, issuer,
  scopes and a SHA-256 hash of the token subject. Tokens are never read or sent.
- **A2A** — `captureA2aCallerIdentity({ agentCard, authenticated,
  cardSignatureVerified })` / `capture_a2a_caller_identity(...)`: identity fields
  of the caller's Agent Card, whether the caller satisfied the auth scheme the
  customer's card declares, and whether the customer verified the card's JWS
  signature.

`batch._apply_agent_protocol_identity` grades it
(`journeys/traffic/protocol_identity.py`) into `server_context.agent_protocol`
and removes the raw block. The classifier ranks it below a verified Web Bot Auth
signature and above user-agent claims.

| Evidence | `proof_level` | `verification_level` | Confidence |
|---|---|---|---|
| A2A caller authenticated + Agent Card signature verified (card origin consistent) | `server_observed` | `a2a_authenticated_signed_card` | 0.9 |
| MCP OAuth client verified by the tenant's server | `server_observed` | `mcp_oauth_client` | 0.85 |
| A2A caller authenticated | `server_observed` | `a2a_authenticated` | 0.8 |
| MCP `clientInfo` only | `declared` | `mcp_client_info_declared` | 0.6 |
| A2A Agent Card only | `declared` | `a2a_agent_card_declared` | 0.6 |

Known client names map to providers (Claude → anthropic, ChatGPT → openai,
Cursor, Gemini, Copilot, Perplexity). The hashed OAuth subject is recorded as
`principal_subject_hash`: a pseudonymous reference to the user who authorized
the client. The agent execution projector turns it into a principal *claim*
(`reported_principal_namespace = "mcp_oauth:<issuer>"`, where `<issuer>` is the
full OAuth issuer identifier — scheme, host, port and path — so two issuers on
one origin, such as `/realms/one` and `/realms/two`, stay distinct; an issuer
longer than 200 characters becomes its origin plus a SHA-256 digest,
`reported_principal_ref = <hash>`) when the producer reported no principal. As
with every claim, the lineage resolver links a human only through a claim
binding for that (namespace, hash), for example one the tenant's identity
resolution writes by hashing its own user ids the same way. Agent Card signatures are verified by the customer's server
(it holds the card and fetches the signer's keys); Aether does not fetch keys.

### 4.4 Mobile automation evidence

The iOS and Android SDKs add `context.device.automation = {testHarness,
emulator}` (React Native inherits it from the native SDKs):

- `testHarness` — Android: `ActivityManager.isUserAMonkey()`, the user test
  harness (API 29+), or an instrumentation framework loaded in the app process
  (Espresso, UiAutomator, Appium's UiAutomator2 server). iOS: XCTest hosting the
  process. Classified `machine` with evidence `actor:mobile_test_harness`.
- `emulator` — Simulator / emulator. Evidence only (`actor:emulator`); it never
  changes the actor, because developers use emulators.

Accessibility services and VoiceOver / Switch Control state are deliberately not
read, so assistive-technology users are never flagged. Limit: XCUITest and
Appium's WebDriverAgent drive an iOS app from a separate process and cannot be
detected reliably from inside the app. The Swift and Kotlin sources are not
compiled in this repository's local checks (`scripts/mobile_build_check.py`
states that it makes no compile claim); their unit tests run in the native CI.

### 4.7 Mobile app attestation (App Attest / Play Integrity)

Opt-in per app (`AetherConfig.deviceIntegrity`, iOS and Android; React Native
forwards `deviceIntegrity`). The SDK asks `POST /sdk/device-integrity/challenge`
for a single-use challenge (stored in the cache, bound to tenant, platform and
the install's anonymous id), attests, and posts it to
`POST /sdk/device-integrity/verify`:

- **iOS — App Attest**, verified offline (`ingestion/device_integrity/app_attest.py`):
  the credential certificate chains to the pinned Apple App Attestation Root CA
  (SHA-256 fingerprint checked at load); `SHA256(authData || SHA256(challenge))`
  matches the nonce extension; the key id is the SHA-256 of the credential key;
  `rpIdHash` matches a configured `<TEAM_ID>.<bundle id>`; counter 0; the AAGUID
  matches the configured environment. A fresh key is attested per token
  lifetime (no per-key server storage).
- **Android — Play Integrity** (`play_integrity.py`): the token is decoded
  through Google's `decodeIntegrityToken` with the configured service account
  (signed JWT-bearer auth, no Google SDK). The nonce, package, timestamp and
  (when configured) signing-certificate digest must match;
  `PLAY_RECOGNIZED` + `MEETS_DEVICE_INTEGRITY`/`MEETS_STRONG_INTEGRITY` →
  `verified`, `MEETS_VIRTUAL_INTEGRITY` → `virtual`, `MEETS_BASIC_INTEGRITY` →
  `basic`, otherwise `failed`. The SDK links the Play library `compileOnly`.

Verify returns an HMAC integrity token (7 days by default) bound to tenant,
anonymous id and platform. The SDK sends it as `context.device.integrity.token`;
`batch._apply_device_integrity` verifies it, records
`server_context.device_integrity`, and always removes the token. Classification:
`failed` → `machine` (not a genuine app on a genuine device); `verified`,
`basic`, `virtual` and an invalid token are evidence only (`device_integrity:<verdict>`),
never proof of a human. Limit: the token is a bearer credential for its
lifetime; per-event App Attest assertions would bind each event to the key.

Configuration (`settings.device_integrity`, documented in
`config/environments/.env.example`): `AETHER_DEVICE_INTEGRITY_ENABLED`, the App
Attest app IDs and environment, the Play package names, certificate digests and
service account JSON, and the token HMAC secret. Until those are set the routes
answer `device_integrity_disabled` / `*_not_configured`. Verified locally:
App Attest against a locally built Apple-shaped certificate chain, Play
Integrity with a stubbed Google transport, the routes end to end, the Android
manager compiled with kotlinc and unit-tested on the JVM, and the Play client
compiled against the real Play Integrity library. Not verified here: a real
device attestation and the Swift build (no Xcode); both need native CI.

### 4.5 Deployment registry on

`AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED` is ON in
`config/release/feature_flags/staging.yaml` (also in `task_environment`, which
the ECS module applies) and in `production.yaml`'s `on` list. The code default in
`settings.py` stays off for local and test environments. For every non-staging
profile the ECS module sets it on the API and worker tasks
(`local.agent_registry_runtime_environment`, controlled by the root variable
`enable_agent_deployment_registry`, default `true`); staging gets it from the
manifest only, so it is never set twice.

### 4.6 Execution verification in Agent 360

Lineage nodes record which verification states their own facts reached
(`execution_verification_states`, `strongest_execution_verification`,
`has_source_reported_facts`). Agent 360's lineage section shows them as
`executionVerification.label`: `signed` (attested), `registry_validated`
(deployment verified), or `source_reported` (unsigned). Any unsigned facts add a
section warning telling the operator to sign them with an attestation key, so
unsigned events never read as verified.

## 5. What we can claim now

- **Can claim:** agents reported through the server SDK are attributed, with
  cryptographic proof for signing deployments. Declared OpenAI and Perplexity
  agents and crawlers are verified against the providers' published ranges.
  Agents that sign with Web Bot Auth (ChatGPT today) are verified even in a
  normal browser. Agents that never run JavaScript are verified when the
  customer forwards request evidence from the server SDK. MCP clients and A2A
  callers are identified from the protocol, verified when the customer's server
  authenticated them. WebDriver-driven browsers and harness-driven mobile apps
  are flagged as automation. Aether
  never counts an actor as human without evidence, and reports how much traffic
  is unresolved.
- **Cannot claim:** that Aether detects agents that hide (unsigned, no
  automation flag), iOS UI automation driven from outside the app, or that
  `unknown` traffic is human.

## 6. Phase 2 — remaining gaps

| Gap | Change | Reaches |
|---|---|---|
| More Web Bot Auth signers | Add signers to `refresh_web_bot_auth_directories.py` as they publish key directories | High per signer |
| Mobile attestation configuration | Set the App Attest app IDs, Play packages / certificate digests / service account and the token secret, enable `AETHER_DEVICE_INTEGRITY_ENABLED`, turn on `deviceIntegrity` in the apps, and run a real-device attestation in native CI | Medium–high once configured |
| Per-event App Attest assertions | Bind each event to the attested key instead of a bearer token | High |
| Providers without published ranges | Add providers to `refresh_agent_provider_ranges.py` as they publish ranges; reverse-DNS verification where documented | High per provider |

Detection with no SDK, server integration, webhook or connector installed is a
separate, unscheduled product question:
[Public Agent Registry](plans/PUBLIC-AGENT-REGISTRY.md).
