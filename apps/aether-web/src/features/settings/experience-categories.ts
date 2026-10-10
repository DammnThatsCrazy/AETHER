/**
 * Settings→Integrations experience-category presentation (WS-1).
 *
 * The ``experience_category`` wire tokens are single-sourced server-side
 * (``shared.integration_contracts.experience``) and pass through the R1
 * transport types untouched. This module only maps those stable tokens onto the
 * §6 customer vocabulary for Settings grouping — it never re-derives categories
 * and never invents new ones. Unknown-but-present tokens fall back to a readable
 * humanization of the snake token so a future category still renders rather
 * than silently collapsing into "Other".
 */

export const EXPERIENCE_CATEGORY_LABELS: Readonly<Record<string, string>> = {
  advertising_campaigns: 'Advertising',
  commerce_revenue: 'Commerce & Revenue',
  crm_customer: 'Customer & CRM',
  communications_lifecycle: 'Communications',
  analytics_behavior: 'Analytics & Behavior',
  social_community: 'Social & Community',
  customer_support: 'Customer Support',
  work_operations: 'Work Operations',
};

/** Canonical grouping order (mirrors the server's EXPERIENCE_CATEGORIES order). */
export const EXPERIENCE_CATEGORY_ORDER: readonly string[] = [
  'advertising_campaigns',
  'commerce_revenue',
  'crm_customer',
  'communications_lifecycle',
  'analytics_behavior',
  'social_community',
  'customer_support',
  'work_operations',
];

/** Label for integrations the catalog does not classify into an experience. */
export const UNCLASSIFIED_EXPERIENCE_LABEL = 'Other';

function humanize(token: string): string {
  return token
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, c => c.toUpperCase());
}

export function experienceCategoryLabel(token: string | null | undefined): string {
  if (!token) return UNCLASSIFIED_EXPERIENCE_LABEL;
  return EXPERIENCE_CATEGORY_LABELS[token] ?? humanize(token);
}

export interface ExperienceGroup<T> {
  /** The raw experience_category wire token ('' for the unclassified bucket). */
  readonly key: string;
  /** §6 customer vocabulary group title. */
  readonly label: string;
  readonly items: readonly T[];
}

/**
 * Group tenant integrations by experience_category in canonical server order,
 * with anything unclassified (null) collected last under the "Other" bucket.
 */
export function groupByExperienceCategory<T extends { readonly experience_category: string | null }>(
  items: readonly T[],
): readonly ExperienceGroup<T>[] {
  const buckets = new Map<string, T[]>();
  let other: T[] = [];
  for (const item of items) {
    const key = item.experience_category;
    if (!key) {
      other = [...other, item];
      continue;
    }
    const bucket = buckets.get(key);
    if (bucket) bucket.push(item);
    else buckets.set(key, [item]);
  }

  const groups: ExperienceGroup<T>[] = [];
  for (const key of EXPERIENCE_CATEGORY_ORDER) {
    const itemsInBucket = buckets.get(key);
    if (itemsInBucket && itemsInBucket.length > 0) {
      groups.push({ key, label: experienceCategoryLabel(key), items: itemsInBucket });
    }
  }
  // Categories that exist server-side but predate this map still render, sorted
  // deterministically after the canonical set.
  for (const key of [...buckets.keys()].sort()) {
    if (!EXPERIENCE_CATEGORY_ORDER.includes(key)) {
      const itemsInBucket = buckets.get(key);
      if (itemsInBucket && itemsInBucket.length > 0) {
        groups.push({ key, label: experienceCategoryLabel(key), items: itemsInBucket });
      }
    }
  }
  if (other.length > 0) {
    groups.push({
      key: '',
      label: UNCLASSIFIED_EXPERIENCE_LABEL,
      items: other,
    });
  }
  return groups;
}
