import type { IconDescriptor } from './types';

export const actionIcons = {
  connect: { icon: 'plug-zap', label: 'Connect provider', decorativeByDefault: false, description: 'Connect an external provider.' },
  configure: { icon: 'settings-2', label: 'Configure', decorativeByDefault: false, description: 'Configure a capability.' },
  retry: { icon: 'rotate-cw', label: 'Retry', decorativeByDefault: false, description: 'Retry the latest operation.' },
  refresh: { icon: 'refresh-cw', label: 'Refresh', decorativeByDefault: false, description: 'Refresh current data.' },
  investigate: { icon: 'search', label: 'Investigate', decorativeByDefault: false, description: 'Open investigation context.' },
  approve: { icon: 'circle-check', label: 'Approve', decorativeByDefault: false, description: 'Approve the presented action.' },
  reject: { icon: 'circle-x', label: 'Reject', decorativeByDefault: false, description: 'Reject the presented action.' },
  pause: { icon: 'circle-pause', label: 'Pause', decorativeByDefault: false, description: 'Pause an active process.' },
  resume: { icon: 'circle-play', label: 'Resume', decorativeByDefault: false, description: 'Resume an active process.' },
  export: { icon: 'file-down', label: 'Export', decorativeByDefault: false, description: 'Export the selected data.' },
} as const satisfies Readonly<Record<string, IconDescriptor>>;

export type Action = keyof typeof actionIcons;
