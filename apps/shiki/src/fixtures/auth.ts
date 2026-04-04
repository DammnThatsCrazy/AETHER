import type { ShikiUser, ShikiRole } from '@shiki/types';

export const MOCK_USERS: Record<ShikiRole, ShikiUser> = {
  shiki_executive_operator: {
    id: 'mock-exec-001',
    email: 'commander@aether.internal',
    displayName: 'Commander Bright',
    role: 'shiki_executive_operator',
    groups: ['shiki_executive_operator', 'executive'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
  shiki_engineering_command: {
    id: 'mock-eng-001',
    email: 'engineer@aether.internal',
    displayName: 'Chief Engineer Amuro',
    role: 'shiki_engineering_command',
    groups: ['shiki_engineering_command', 'engineering'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
  shiki_specialist_operator: {
    id: 'mock-spec-001',
    email: 'specialist@aether.internal',
    displayName: 'Specialist Sayla',
    role: 'shiki_specialist_operator',
    groups: ['shiki_specialist_operator', 'specialist'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
  shiki_observer: {
    id: 'mock-obs-001',
    email: 'observer@aether.internal',
    displayName: 'Observer Kai',
    role: 'shiki_observer',
    groups: ['shiki_observer'],
    avatarUrl: undefined,
    lastLogin: new Date().toISOString(),
  },
};
