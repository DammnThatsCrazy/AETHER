/**
 * Plans for the pricing page and /app signup. Numbers come from plans.json,
 * which mirrors services/api/shared/plans/catalog.py (kept in sync by
 * tests/unit/test_site_plans_match_catalog.py). Copy lives here.
 */
import data from './plans.json';
import type { Accent } from './palette';

export type SelfServePlanId = 'alpha' | 'beta' | 'gamma' | 'delta';
export type Interval = 'monthly' | 'annual';

export interface SelfServePlan {
  id: SelfServePlanId;
  name: string;
  fit: string;
  accent: Accent;
  monthly: number;
  annual: number;
  monthlyQuota: number;
  memberCap: number;
  burstRpm: number;
  serviceCount: number;
  eventOveragePer1k: string;
}

const FIT: Record<SelfServePlanId, [string, Accent]> = {
  alpha: ['Establish the first governed connection.', 'sage'],
  beta: ['Add business-system and identity context.', 'cobalt'],
  gamma: ['Operate perspectives in real workflows.', 'ochre'],
  delta: ['Expand sources, volume, and governance.', 'solar'],
};

export const SELF_SERVE_PLANS: SelfServePlan[] = data.self_serve.map((p) => {
  const id = p.id as SelfServePlanId;
  return {
    id,
    name: p.name,
    fit: FIT[id][0],
    accent: FIT[id][1],
    monthly: p.monthly,
    annual: p.annual,
    monthlyQuota: p.monthly_quota,
    memberCap: p.member_cap,
    burstRpm: p.burst_rpm,
    serviceCount: p.service_count,
    eventOveragePer1k: p.event_overage_per_1k,
  };
});

/** The plan most teams start with; highlighted on the pricing page. */
export const SUGGESTED_PLAN: SelfServePlanId = 'beta';

export const CONTRACT_PLANS = data.contract;

/**
 * Price values are shown only when the build opts in. The older pricing page
 * held prices back until a commercial plan is approved; production keeps that
 * rule until VITE_PUBLISH_PRICES is set for it.
 */
export function pricesPublished(env: { VITE_PUBLISH_PRICES?: string } = import.meta.env): boolean {
  return env.VITE_PUBLISH_PRICES === 'true';
}

export function formatPrice(amount: number): string {
  return amount === 0 ? '$0' : `$${amount.toLocaleString('en-US')}`;
}

/** 9000000 → "9M" */
export function formatQuota(events: number): string {
  return events >= 1_000_000 ? `${events / 1_000_000}M` : events.toLocaleString('en-US');
}
