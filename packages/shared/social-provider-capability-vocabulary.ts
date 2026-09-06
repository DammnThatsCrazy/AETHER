/**
 * DO NOT EDIT — generated from packages/shared/contracts/social-provider-capability-vocabulary.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const socialProviderCapabilityVocabularySchemaVersion = '1.0.0' as const;
export const socialProviderCapabilityVocabularyContractVersion = '1.0.0' as const;

/** Canonical description of the UPR social capability vocabulary. */
export const socialProviderCapabilityVocabularyDescription = 'Canonical social provider capability vocabulary for UPR social convergence (blueprint §§15-19). Providers declare ONLY what they genuinely support under the UPR grammar family.product.capability. A provider that cannot expose follower relationships must not claim relationship_read. Providers with limited API access return not_supported | not_authorized | credential_waiting rather than empty success. code_complete is never promoted to partner_live without external evidence. Consumed by Milestone M2 UPR social plugins; published as generated py/ts contract twins.' as const;

/** Canonical social-provider capability grammar (family.product.capability). */
export const socialProviderCapabilityGrammar = 'family.product.capability' as const;

/** Capabilities a social provider may declare under the UPR grammar. */
export const socialProviderCapabilities = [
  'account_read',
  'content_read',
  'relationship_read',
  'interaction_read',
  'community_read',
  'metrics_read',
  'incremental_pull',
  'backfill',
  'webhook_receive',
  'deletion_observe',
] as const;
export type SocialProviderCapability = typeof socialProviderCapabilities[number];

/** Acquisition classes describing how a social provider capability was acquired. */
export const socialProviderAcquisitionClasses = [
  'olympus_managed',
  'tenant_connected',
  'tenant_imported',
  'tenant_first_party',
] as const;
export type SocialProviderAcquisitionClass = typeof socialProviderAcquisitionClasses[number];

/** Lifecycle states a social provider capability may occupy. */
export const socialProviderLifecycleStates = [
  'code_complete',
  'credential_waiting',
  'rights_waiting',
  'compliance_review',
  'sandbox_validated',
  'partner_live',
] as const;
export type SocialProviderLifecycleState = typeof socialProviderLifecycleStates[number];

/** States that must return an explicit negative result rather than empty success. */
export const socialProviderEmptySuccessForbiddenStates = [
  'not_supported',
  'not_authorized',
  'credential_waiting',
] as const;
export type SocialProviderEmptySuccessForbiddenState = typeof socialProviderEmptySuccessForbiddenStates[number];

/** Example well-formed social capability identities (family.product.capability). */
export const socialProviderExampleCapabilities = [
  'reddit.social.account_read',
  'reddit.social.content_read',
  'x.social.relationship_read',
  'farcaster.social.interaction_read',
  'youtube.social.metrics_read',
] as const;

/** Rules constraining social-provider capability declarations. */
export const socialProviderCapabilityRules = [
  'relationship_read must only be claimed by providers that genuinely expose follower/relationship data',
  'limited API access must return not_supported | not_authorized | credential_waiting, never empty success',
  'code_complete must not be promoted to partner_live without external evidence',
  'social provider ingestion may remain code_complete / externally_blocked without live credentials — honest status, not a defect',
  'every social record is evaluated for source license, allowed collection/storage/graph-projection/display/derived-analysis/model-use, retention, and deletion behavior',
] as const;
