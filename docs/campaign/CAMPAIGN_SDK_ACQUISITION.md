---
title: Campaign SDK Acquisition Evidence
slug: campaign/campaign-sdk-acquisition
section: sdks
visibility: I
audience: [dev-junior, dev-senior]
source_files:
  - packages/shared/acquisition-evidence.ts
  - packages/web/src/types.ts
  - packages/web/src/index.ts
  - packages/web/src/tracking/traffic-source-tracker.ts
last_synced_commit: "bee65298"
---

# Campaign SDK Acquisition Evidence

`AcquisitionEvidence` is the shared contract for raw campaign and referral evidence captured at landing. The web SDK's emitted wire field is `context.trafficSource`, produced by `TrafficSourceTracker`. Both structures contain observations only: the SDK does not classify a channel, provider, product, actor, or campaign from them.

## Interface

```typescript
interface AcquisitionEvidence {
  // UTM parameters
  utmSource?: string;
  utmMedium?: string;
  utmCampaign?: string;       // utm_campaign value (not the campaign display name)
  utmContent?: string;
  utmTerm?: string;
  utmId?: string;             // utm_id — highest-confidence UTM signal

  // Platform identity
  platform?: string;
  externalAccountId?: string;
  externalCampaignId?: string;
  canonicalCampaignId?: string;  // Aether UUID (validated server-side before use)

  // Click IDs (preserved as evidence; not used for auto-resolution)
  clickIds?: {
    gclid?: string;
    fbclid?: string;
    msclkid?: string;
    ttclid?: string;
    liEFatId?: string;
    rdtCid?: string;
    [key: string]: string | undefined;
  };

  // Landing context
  referrer?: string;
  referrerDomain?: string;
  landingPage?: string;
  referralToken?: string;     // opaque aether_ref value; verified server-side
  entryMethod?: string;       // how the entry evidence was physically observed (web_referrer, android_install_referrer, ios_universal_link, ...)
  destinationDomain?: string; // host of the destination the user LANDED on (deep/universal link host); never the referrer
  destinationPathHash?: string; // one-way hash of the destination path when path privacy is configured
  firstTouch?: boolean;       // true when this is the persisted first touch (vs latest touch)

  // Session metadata
  firstCapturedAt?: string;   // ISO 8601
  lastObservedAt?: string;
  evidenceExpiresAt?: string; // ISO 8601 — when this evidence stops attaching to new events
  sessionId?: string;
  schemaVersion: number;      // Currently 3

  /** @deprecated Use utmCampaign instead */
  name?: string;
  /** @deprecated Use externalCampaignId instead */
  campaignId?: string;
}
```

`ACQUISITION_EVIDENCE_SCHEMA_VERSION` is `3`. Version 2 added only the optional `referralToken`; version 3 adds the optional `entryMethod`, `destinationDomain`, `destinationPathHash`, `firstTouch`, and `evidenceExpiresAt` fields. Older version payloads remain valid inputs.

## Web event context

The web SDK automatically emits the following raw first-touch shape as `context.trafficSource`:

```typescript
interface TrafficSourceData {
  referrer: string;
  referrerDomain: string;
  utmSource?: string | null;
  utmMedium?: string | null;
  utmCampaign?: string | null;
  utmTerm?: string | null;
  utmContent?: string | null;
  referralToken?: string | null;
  clickIds: Record<string, string>;
  landingPage: string;
}
```

The tracker reads `referralToken` directly from the `aether_ref` query parameter and forwards it unchanged. `TrafficSourceData` intentionally has no classified channel, provider, product, or actor fields.

## Shared helper

```typescript
import { evidenceFromSearchParams, ACQUISITION_EVIDENCE_SCHEMA_VERSION } from '@aether/shared';

// For integrations that need the shared schema-versioned representation:
const evidence = evidenceFromSearchParams(new URLSearchParams(window.location.search));
```

The standard web SDK does not emit a separate `context.acquisitionEvidence` field. It emits `context.trafficSource` automatically through its normal event queue.

## Deprecated fields

`name` (replaced by `utmCampaign`) and `campaignId` (replaced by `externalCampaignId`) are forwarded for one SDK release window and then removed. Do not use them in new integrations.

## SPA navigation

Capture `AcquisitionEvidence` on first landing only. Do not re-capture on client-side navigation — the first landing URL is the attribution source.

The web SDK applies the same rule to `context.trafficSource`: it captures `aether_ref` as `referralToken` on the first landing and retains that exact token across SPA navigation for the remainder of the browser session.

## Security notes

- `canonicalCampaignId` is validated server-side against tenant ownership; a forged UUID is rejected.
- Click IDs are stored as evidence but do not trigger auto-resolution without a registered alias.
- `referralToken` is opaque to the SDK. Its presence does not assert a campaign, AI provider, product, referring actor, or verification level. The server must verify the token before deriving any of those dimensions.
- Never log `referralToken`, `externalCampaignId`, or `canonicalCampaignId` values in client-side error reporters.
