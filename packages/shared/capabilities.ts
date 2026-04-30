// =============================================================================
// Aether SDK — Shared Capability Manifest
// Returned by GET /v1/config so SDKs know which event families, purposes,
// and rails the backend currently activates. See docs/source-of-truth/
// CAPABILITY_MANIFEST.md.
// =============================================================================

import type { EventFamily } from './events';
import type { ConsentPurpose } from './consent';
import type { VMType } from './wallet';
import type { Rail } from './provenance';

/** Intelligence Graph layer activations — mirrors backend IntelligenceGraphConfig. */
export interface GraphLayerFlags {
  agent: boolean;     // IG_AGENT_LAYER (L2)
  commerce: boolean;  // IG_COMMERCE_LAYER (L3a)
  x402: boolean;      // IG_X402_LAYER (L3b)
  onchain: boolean;   // IG_ONCHAIN_LAYER (L0)
  trust_scoring?: boolean;
}

/** Canonical capability manifest. */
export interface CapabilityManifest {
  schemaVersion: string;
  /** Which event families the backend is currently ingesting. */
  activeFamilies: EventFamily[];
  /** Which consent purposes the backend recognizes. */
  supportedPurposes: ConsentPurpose[];
  /** Which payment rails the commerce plane accepts. */
  activeRails: Rail[];
  /** Which VMs the wallet/transaction pipeline currently supports. */
  supportedVMs: VMType[];
  /** Intelligence Graph layer activations. */
  layers: GraphLayerFlags;
  /** Optional backend-delivered feature flags (opaque to SDK). */
  featureFlags?: { key: string; enabled: boolean; value?: unknown }[];
}
