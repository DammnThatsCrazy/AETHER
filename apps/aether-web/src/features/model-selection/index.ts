/**
 * Public barrel for the tenant model-selection feature (ADR-008 D9).
 *
 * Exposes the four surfaces (panel, registry view, entitlement badge, evidence
 * references), the `useModelSelection` hook, the typed server-shaped contract
 * (types), and the typed fetch client. None of these ever carry credentials or
 * API keys.
 */
export { ModelSelectionPanel } from './ModelSelectionPanel';
export { ModelRegistryView } from './ModelRegistryView';
export { useModelSelection } from './useModelSelection';
export { EntitlementBadge } from './EntitlementBadge';
export { EvidenceReferences } from './EvidenceReferences';
export { defaultModelSelectionApi } from './types';
export type {
  EvidenceRef,
  ModelListResponse,
  ModelRegistryModel,
  TenantModelSelectionApi,
} from './types';
