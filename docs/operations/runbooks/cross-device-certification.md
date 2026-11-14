---
title: "Cross-Device Journey Certification (XD-1)"
slug: runbooks/cross-device-certification
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: experimental
since_version: "0.1.0-alpha.0"
canonical_owner: platform@aether
source_files:
  - scripts/cross_device_certification.py
  - services/api/journeys/handoff/continuation_scope.py
  - services/api/journeys/handoff/continuation_jobs.py
  - services/api/journeys/traffic/apple_ads_attribution.py
  - services/api/journeys/measurement/activity_rebuild.py
source_hashes:
  "scripts/cross_device_certification.py": "sha256:b3585d897f56d506e012de5b85085871944103d56b071c7d0ab52f732b74f69d"
  "services/api/journeys/handoff/continuation_jobs.py": "sha256:13081b7ff46f57f7ae26c005163275d92cef3b7e7bf52959c02df345b0292630"
  "services/api/journeys/handoff/continuation_scope.py": "sha256:4805ff2560480a30d0e5452eefdd92dfc500cc6f84109ad10f5dc38de4e6ad08"
  "services/api/journeys/measurement/activity_rebuild.py": "sha256:f9a05aefbcb77f51aad95b980405b761e5f557cec88a8baf2d72334bcf7286c8"
  "services/api/journeys/traffic/apple_ads_attribution.py": "sha256:16eac054fed62dcb1a4761d871d41241c773d8edd2c547a066247b5dacfe823b"
---

# Cross-Device Journey Certification (XD-1)

This runbook certifies one scenario on real devices against a live tenant. A
person reaches the mobile app from an ad, browses anonymously, drops, picks up
on a desktop browser, logs in, and then delegates work to agents.

There are three levels of evidence. Do not report one as another.

| Level | What it shows | How |
|---|---|---|
| Code | The routes, compiler, jobs and repositories link the scenario correctly in one process. | `services/api/tests/measurement/test_cross_device_agent_loop.py` (CI) |
| One real run | The same links hold for one real run on real devices on one tenant. | This runbook plus `scripts/cross_device_certification.py` |
| Measured accuracy | False-merge and false-split rates on independently labelled pairs. | The identity calibration pilot (section 5) |

Passing a real run is not an accuracy rate. Anonymous visitors with no handoff
and no login are never linked. That is intended, not a gap in the test.

## 1. Preconditions (staging)

| Setting | Value | Why |
|---|---|---|
| `JOURNEY_HANDOFF_ENABLED` | on (staging manifest `task_environment`) | Issue and redeem handoff tokens |
| `JOURNEY_ACTIVITY_REBUILD_ENABLED` | on (staging manifest `task_environment`) | New activity recompiles its journey |
| `AETHER_APPLE_ADS_ATTRIBUTION_ENABLED` | on, only for an iOS Apple Ads run | Server exchange with `api-adservices.apple.com` (egress must be allowed) |
| `maintenance` worker role running | yes | Runs the `journey.handoff_continuation` job |
| Identity-link consent | granted on both devices | Redemption checks consent on both ends |

Check the flags with `make production-status` or the staging flag manifest.
Production keeps all three off.

## 2. Devices and builds

- An iOS build with the Aether SDK. Call `resolveAppleAdsAttribution` once after
  `initialize`, and use `createJourneyHandoff` / `redeemJourneyHandoff`.
- For Android, the Play install referrer is captured automatically.
- A desktop browser with the web SDK, calling `redeemJourneyHandoff` with the
  token from the link or QR code.

Acquisition paths by platform:

| Path | Proof level | Notes |
|---|---|---|
| iOS, Apple Ads | `platform_verified` (server-verified token) | Apple Ads campaigns only |
| iOS, other ad networks | none at user level | Use a partner-controlled link with deferred attribution, or accept Direct / Unknown. SKAdNetwork postbacks stay campaign-level |
| Android, Play referrer | `platform_verified` | Click-level when the network passes the referrer |

## 3. Run

1. On the phone, open the ad (or partner link) and install the app. Record
   `getAnonymousId()`.
2. Browse at least two screens, then create a handoff. Open its link or QR code
   on the desktop. Close the app.
3. On the desktop, the web SDK redeems the token. Record `getAnonymousId()`.
   Browse, then log in. Record the profile ID.
4. Grant an agent a delegation from that person and let it run one tool call.
5. Wait for the continuation job and the activity rebuild window (30 seconds by
   default, `AETHER_JOURNEY_ACTIVITY_REBUILD_WINDOW_SECONDS`).

## 4. Collect evidence

```bash
AETHER_CERT_API_KEY=<read key> .venv/bin/python scripts/cross_device_certification.py \
  --base-url https://<staging api> \
  --mobile-anonymous-id <phone id> --desktop-anonymous-id <desktop id> \
  --profile-id <profile id> --expect-acquisition ios_apple_ads_attribution \
  --out evidence/xd1-$(date +%Y%m%d).json
```

The script only reads. It checks that:

- the mobile (root) anonymous ID owns the only current continuation journey;
- the desktop end has no standalone journey;
- the steps span both sessions with an `explicit_handoff` hop;
- the first step is the acquisition;
- after login, the profile journey contains every continuation session and
  still starts at the acquisition.

It exits non-zero if any check fails. For the agent side, read Profile 360 for
the person (`agent_delegations` section, with an `agent:manage` caller) or
`GET /v1/agent/agents/principals/{entity_id}/agents`.

Then repeat the negative controls by hand:

- redeeming the same token again is refused;
- a token from another tenant or app is refused;
- a desktop visitor with no handoff and no login keeps a journey of its own.

## 5. Identity accuracy (pilot, separate)

Accuracy needs human-reviewed identity pairs from the partner pilot, with
tenant, source and time coverage. Use the existing tools:

```bash
.venv/bin/python scripts/identity_confidence_calibration_intake.py prepare <review_export.jsonl> <packet_dir>
```

```bash
.venv/bin/python scripts/identity_confidence_calibration_intake.py assemble ...
```

```bash
.venv/bin/python scripts/identity_confidence_calibration_evaluation.py <labels.jsonl> --output <report.json>
```

The evaluation reports `evidence_sufficient_for_policy_review` only when its
label, provenance and band-support gates are met. It always reports
`production_calibrated: false`. See
`docs/architecture/blueprints/identity-continuity/confidence-calibration.md`.

## 6. What the continuation does and does not do

- It compiles the activity of every anonymous ID reachable through redeemed
  handoffs into one journey, owned by the device the journey started on.
- The walk is bounded at 16 anonymous IDs and 8 hops; a truncated walk is
  logged.
- It never merges identities, rewrites anonymous IDs or feeds identity
  resolution.
- A profile journey takes in handoff-linked anonymous activity only when no
  other profile already owns that activity.
- Erasing a subject's handoffs (DSR) removes the link. The next compile builds
  separate journeys again.
