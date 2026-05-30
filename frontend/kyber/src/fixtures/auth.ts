import type { KyberUser, KyberRole } from '@kyber/types';

export const MOCK_USERS: Record<KyberRole, KyberUser> = {
  kyber_executive_operator: {
    id: 'mock-exec-001',
    email: 'commander@aether.internal',
    displayName: 'Commander Bright',
    role: 'kyber_executive_operator',
    groups: ['kyber_executive_operator', 'executive'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
  kyber_engineering_command: {
    id: 'mock-eng-001',
    email: 'engineer@aether.internal',
    displayName: 'Chief Engineer Amuro',
    role: 'kyber_engineering_command',
    groups: ['kyber_engineering_command', 'engineering'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
  kyber_specialist_operator: {
    id: 'mock-spec-001',
    email: 'specialist@aether.internal',
    displayName: 'Specialist Sayla',
    role: 'kyber_specialist_operator',
    groups: ['kyber_specialist_operator', 'specialist'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
  kyber_observer: {
    id: 'mock-obs-001',
    email: 'observer@aether.internal',
    displayName: 'Observer Kai',
    role: 'kyber_observer',
    groups: ['kyber_observer'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
};
