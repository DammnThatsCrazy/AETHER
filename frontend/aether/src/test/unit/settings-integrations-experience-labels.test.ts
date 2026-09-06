import { describe, expect, it } from 'vitest';
import {
  EXPERIENCE_CATEGORY_LABELS,
  groupByExperienceCategory,
  experienceCategoryLabel,
} from '@aether-app/features/settings';

interface Stub {
  readonly id: string;
  readonly experience_category: string | null;
}

const item = (id: string, experience_category: string | null): Stub => ({ id, experience_category });

describe('features/settings experience-category presentation', () => {
  it('maps the eight server wire tokens to the §6 customer vocabulary', () => {
    expect(EXPERIENCE_CATEGORY_LABELS).toEqual({
      advertising_campaigns: 'Advertising',
      commerce_revenue: 'Commerce & Revenue',
      crm_customer: 'Customer & CRM',
      communications_lifecycle: 'Communications',
      analytics_behavior: 'Analytics & Behavior',
      social_community: 'Social & Community',
      customer_support: 'Customer Support',
      work_operations: 'Work Operations',
    });
  });

  it('labels every canonical token and buckets unknown tokens to Other/null', () => {
    expect(experienceCategoryLabel('advertising_campaigns')).toBe('Advertising');
    expect(experienceCategoryLabel('communications_lifecycle')).toBe('Communications');
    expect(experienceCategoryLabel(null)).toBe('Other');
    expect(experienceCategoryLabel(undefined)).toBe('Other');
    expect(experienceCategoryLabel('')).toBe('Other');
  });

  it('humanizes an unknown future token rather than hiding it', () => {
    expect(experienceCategoryLabel('loyalty_rewards')).toBe('Loyalty Rewards');
  });

  it('groups items in canonical server order and collects unclassified last', () => {
    const groups = groupByExperienceCategory([
      item('a', 'communications_lifecycle'),
      item('b', null),
      item('c', 'advertising_campaigns'),
      item('d', 'commerce_revenue'),
      item('e', 'advertising_campaigns'),
    ]);

    expect(groups.map(g => [g.key, g.label, g.items.length])).toEqual([
      ['advertising_campaigns', 'Advertising', 2],
      ['commerce_revenue', 'Commerce & Revenue', 1],
      ['communications_lifecycle', 'Communications', 1],
      ['', 'Other', 1],
    ]);
  });

  it('renders groups with no items as absent (no empty section headers)', () => {
    const groups = groupByExperienceCategory([
      item('only', 'crm_customer'),
      item('noclass', null),
    ]);
    expect(groups.map(g => g.key)).toEqual(['crm_customer', '']);
  });
});
