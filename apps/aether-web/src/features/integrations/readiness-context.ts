/**
 * Contextual readiness advisor (WS-4, additive).
 *
 * Pure projection over the tenant-contextual readiness graph that turns the
 * wire items into the two honest, page-level actions the contextual-CTAs need:
 *
 *   - ``attention`` — tenant integrations whose own evidence says they need
 *     attention (a credential is missing on a connected integration, sync is
 *     failing/degraded, or the provider was pulled to an off-ramp). These are
 *     *facts* about the tenant's own records; any surface may surface them.
 *   - ``connect`` — the first *dependent* experience category (the page's
 *     declared data needs, e.g. a paid-search campaign depends on Advertising)
 *     for which the tenant has NOT engaged any integration. This is "an
 *     integration is connected but a needed one is not": only categories where
 *     no connected/ready/disabled/needs-attention record exists qualify, so we
 *     never nag about a category the tenant has already wired up.
 *
 * Honesty rules honored here:
 *   * The vocabulary is the §6 set (Connect / Connected / Needs attention /
 *     Ready / Syncing); no capability-readiness token is invented client-side.
 *   * ``connect`` is a *suggestion*, never a readiness claim — the page copy
 *     says data appears after a source is connected *and syncing*, and the
 *     destination (Settings→Integrations) owns the live state.
 */
import type { TenantReadinessItem } from './types';

export const TENANT_STATE_AVAILABLE = 'available';
export const TENANT_STATE_CONNECTED = 'connected';
export const TENANT_STATE_READY = 'ready';
export const TENANT_STATE_CONNECTION_DISABLED = 'connection_disabled';
export const TENANT_STATE_NEEDS_ATTENTION = 'needs_attention';

/** §6 UX display labels for the eight customer experience categories. */
export const EXPERIENCE_CATEGORY_LABELS: Record<string, string> = {
  advertising_campaigns: 'Advertising',
  commerce_revenue: 'Commerce & Revenue',
  crm_customer: 'Customer & CRM',
  communications_lifecycle: 'Communications',
  analytics_behavior: 'Analytics & Behavior',
  social_community: 'Social & Community',
  customer_support: 'Customer Support',
  work_operations: 'Work Operations',
};

export function experienceCategoryLabel(category: string): string {
  return EXPERIENCE_CATEGORY_LABELS[category] ?? category;
}

/** Human phrasing for a concrete attention-reason token (evidence only). */
export const ATTENTION_REASON_LABELS: Record<string, string> = {
  provider_off_ramp: 'Provider is no longer available',
  sync_failed: 'Sync is failing',
  sync_degraded: 'Sync is degraded',
  credential_missing: 'Credentials are missing',
};

export function attentionReasonLabel(reason: string): string {
  return ATTENTION_REASON_LABELS[reason] ?? reason;
}

export interface ReadinessConnectCandidate {
  /** Experience-category wire token (e.g. advertising_campaigns). */
  category: string;
  /** §6 display label (e.g. Advertising). */
  categoryLabel: string;
}

export interface ContextualReadiness {
  /** Tenant integrations whose own evidence says they need attention. */
  attention: TenantReadinessItem[];
  /**
   * First dependent category with NO engaged integration, or null when every
   * dependent category already has at least one engaged/connected integration.
   */
  connect: ReadinessConnectCandidate | null;
}

/** Tenant states that count as "the tenant has already wired up this category". */
const ENGAGED_STATES = new Set<string>([
  TENANT_STATE_CONNECTED,
  TENANT_STATE_READY,
  TENANT_STATE_CONNECTION_DISABLED,
  TENANT_STATE_NEEDS_ATTENTION,
]);

export function contextualReadiness(
  items: TenantReadinessItem[] | undefined,
  dependentCategories: readonly string[],
): ContextualReadiness {
  const list = items ?? [];
  const attention = list.filter(
    (i) => i.tenant_state === TENANT_STATE_NEEDS_ATTENTION,
  );

  let connect: ReadinessConnectCandidate | null = null;
  for (const category of dependentCategories) {
    const members = list.filter((i) => i.experience_category === category);
    if (members.length === 0) continue;
    const anyEngaged = members.some((i) => ENGAGED_STATES.has(i.tenant_state));
    if (!anyEngaged) {
      connect = { category, categoryLabel: experienceCategoryLabel(category) };
      break;
    }
  }

  return { attention, connect };
}
