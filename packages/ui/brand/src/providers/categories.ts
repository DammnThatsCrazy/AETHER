/** Provider categories describe what a platform is, never its health or severity. */
export const providerCategories = [
  'communications',
  'commerce',
  'payments',
  'identity',
  'analytics',
  'social',
  'blockchain',
  'delivery',
  'authentication',
  'infrastructure',
  'productivity',
  'advertising',
  'market-data',
  'intelligence',
  'other',
] as const;

export type ProviderCategory = (typeof providerCategories)[number];

export const providerCategoryLabels: Record<ProviderCategory, string> = {
  communications: 'Communications',
  commerce: 'Commerce',
  payments: 'Payments',
  identity: 'Identity',
  analytics: 'Analytics',
  social: 'Social',
  blockchain: 'Blockchain data',
  delivery: 'Delivery',
  authentication: 'Authentication',
  infrastructure: 'Infrastructure',
  productivity: 'Productivity',
  advertising: 'Advertising',
  'market-data': 'Market data',
  intelligence: 'Intelligence',
  other: 'Other',
};
