import type { ReactNode } from 'react';
import type { ActionClass } from '@shiki/types';
import { usePermissions } from './permissions';

interface PermissionGateProps {
  readonly children: ReactNode;
  readonly requires?: 'canApprove' | 'canIntervene' | 'canCommand' | 'canDiagnose' | 'canRevert' | 'canWriteNotes' | 'canExport';
  readonly actionClass?: ActionClass;
  readonly fallback?: ReactNode;
}

export function PermissionGate({ children, requires, actionClass, fallback }: PermissionGateProps) {
  const perms = usePermissions();

  if (requires && !perms[requires]) {
    return fallback ? <>{fallback}</> : null;
  }

  if (actionClass !== undefined) {
    const check = perms.checkAction(actionClass);
    if (!check.allowed) {
      return fallback ? <>{fallback}</> : null;
    }
  }

  return <>{children}</>;
}
