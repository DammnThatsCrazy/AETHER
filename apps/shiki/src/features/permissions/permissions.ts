import type { ShikiRole, ActionClass, AutomationPosture } from '@shiki/types';
import { useAuth } from '@shiki/features/auth';
import { env } from '@shiki/lib/env';

export interface PermissionCheck {
  readonly allowed: boolean;
  readonly reason?: string;
  readonly requiresApproval: boolean;
  readonly approvalClass?: ActionClass;
}

const ROLE_MAX_ACTION_CLASS: Record<ShikiRole, ActionClass> = {
  shiki_executive_operator: 4,
  shiki_engineering_command: 5,
  shiki_specialist_operator: 2,
  shiki_observer: 0,
};

const ROLE_PERMISSIONS: Record<ShikiRole, {
  readonly canApprove: boolean;
  readonly canIntervene: boolean;
  readonly canCommand: boolean;
  readonly canDiagnose: boolean;
  readonly canRevert: boolean;
  readonly canWriteNotes: boolean;
  readonly canViewDiagnostics: boolean;
  readonly canViewAll: boolean;
  readonly canExport: boolean;
}> = {
  shiki_executive_operator: {
    canApprove: true,
    canIntervene: true,
    canCommand: false,
    canDiagnose: false,
    canRevert: true,
    canWriteNotes: true,
    canViewDiagnostics: true,
    canViewAll: true,
    canExport: true,
  },
  shiki_engineering_command: {
    canApprove: true,
    canIntervene: true,
    canCommand: true,
    canDiagnose: true,
    canRevert: true,
    canWriteNotes: true,
    canViewDiagnostics: true,
    canViewAll: true,
    canExport: true,
  },
  shiki_specialist_operator: {
    canApprove: false,
    canIntervene: false,
    canCommand: false,
    canDiagnose: false,
    canRevert: false,
    canWriteNotes: true,
    canViewDiagnostics: true,
    canViewAll: true,
    canExport: false,
  },
  shiki_observer: {
    canApprove: false,
    canIntervene: false,
    canCommand: false,
    canDiagnose: false,
    canRevert: false,
    canWriteNotes: false,
    canViewDiagnostics: true,
    canViewAll: true,
    canExport: false,
  },
};

export function getMaxActionClass(role: ShikiRole): ActionClass {
  return ROLE_MAX_ACTION_CLASS[role];
}

export function canPerformAction(role: ShikiRole, actionClass: ActionClass, posture?: AutomationPosture): PermissionCheck {
  const maxClass = getMaxActionClass(role);
  const currentPosture = posture ?? (env.VITE_AUTOMATION_POSTURE as AutomationPosture);

  if (actionClass > maxClass) {
    return { allowed: false, reason: `Action class ${actionClass} exceeds role maximum ${maxClass}`, requiresApproval: false };
  }

  // In production observer mode, only class 0 is auto-allowed
  if (env.VITE_SHIKI_ENV === 'production' && actionClass > 0) {
    // Conservative: everything above class 0 needs approval
    if (currentPosture === 'conservative' && actionClass >= 1) {
      return { allowed: true, requiresApproval: true, approvalClass: actionClass };
    }
    // Balanced: class 1-2 auto, 3+ needs approval
    if (currentPosture === 'balanced' && actionClass >= 3) {
      return { allowed: true, requiresApproval: true, approvalClass: actionClass };
    }
    // Aggressive: class 1-3 auto, 4+ needs approval
    if (currentPosture === 'aggressive' && actionClass >= 4) {
      return { allowed: true, requiresApproval: true, approvalClass: actionClass };
    }
  }

  return { allowed: true, requiresApproval: false };
}

export function usePermissions() {
  const { user } = useAuth();
  const role = user?.role ?? 'shiki_observer';
  const perms = ROLE_PERMISSIONS[role];

  return {
    role,
    ...perms,
    maxActionClass: getMaxActionClass(role),
    checkAction: (actionClass: ActionClass) => canPerformAction(role, actionClass),
  };
}
