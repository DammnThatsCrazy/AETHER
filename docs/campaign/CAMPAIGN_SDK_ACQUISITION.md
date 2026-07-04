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
last_synced_commit: cb00c2e3
---

# Campaign SDK Acquisition Evidence

`AcquisitionEvidence` is the canonical contract for capturing all campaign attribution signals at user landing. It is captured once on first page load, preserved across SPA navigations, and forwarded as part of every SDK event context.

## Interface

```typescript
interface AcquisitionEvidence {
  // UTM parameters
  source?: string;
  medium?: string;
  campaign?: string;          // utm_campaign value (not the campaign display name)
  content?: string;
  term?: string;
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
  };

  // Landing context
  referrer?: string;
  referrerDomain?: string;
  landingPage?: string;

  // Session metadata
  firstCapturedAt?: string;   // ISO 8601
  lastObservedAt?: string;
  sessionId?: string;
  schemaVersion: number;      // Always set to ACQUISITION_EVIDENCE_SCHEMA_VERSION

  /** @deprecated Use campaign instead */
  name?: string;
  /** @deprecated Use externalCampaignId instead */
  campaignId?: string;
}
```

## SDK integration

```typescript
import { evidenceFromSearchParams, ACQUISITION_EVIDENCE_SCHEMA_VERSION } from '@aether/shared';

// On page load:
const evidence = evidenceFromSearchParams(new URLSearchParams(window.location.search));
// Store in session storage and forward with all events.
```

## Deprecated fields

`name` (replaced by `campaign`) and `campaignId` (replaced by `externalCampaignId`) are forwarded for one SDK release window and then removed. Do not use them in new integrations.

## SPA navigation

Capture `AcquisitionEvidence` on first landing only. Do not re-capture on client-side navigation — the first landing URL is the attribution source.

## Security notes

- `canonicalCampaignId` is validated server-side against tenant ownership; a forged UUID is rejected.
- Click IDs are stored as evidence but do not trigger auto-resolution without a registered alias.
- Never log `externalCampaignId` or `canonicalCampaignId` values in client-side error reporters.
