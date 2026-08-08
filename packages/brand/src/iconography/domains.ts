import type { IconDescriptor } from './types';

export const domainIcons = {
  identity: { icon: 'fingerprint', label: 'Identity', decorativeByDefault: true, description: 'Identity and profile domain.' },
  commerce: { icon: 'shopping-cart', label: 'Commerce', decorativeByDefault: true, description: 'Commerce and revenue domain.' },
  payments: { icon: 'banknote', label: 'Payments', decorativeByDefault: true, description: 'Payment rails and reconciliation domain.' },
  security: { icon: 'shield', label: 'Security', decorativeByDefault: true, description: 'Security and access-control domain.' },
  intelligence: { icon: 'brain', label: 'Intelligence', decorativeByDefault: true, description: 'Intelligence and decision-support domain.' },
  operations: { icon: 'wrench', label: 'Operations', decorativeByDefault: true, description: 'Operator and reliability domain.' },
  integrations: { icon: 'plug', label: 'Integrations', decorativeByDefault: true, description: 'Third-party integration domain.' },
  data: { icon: 'database', label: 'Data', decorativeByDefault: true, description: 'Data ingestion and quality domain.' },
  delivery: { icon: 'send', label: 'Delivery', decorativeByDefault: true, description: 'Outcome and message delivery domain.' },
} as const satisfies Readonly<Record<string, IconDescriptor>>;

export type Domain = keyof typeof domainIcons;
