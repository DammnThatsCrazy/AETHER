interface PermissionRecord {
  readonly domain?: unknown;
  readonly action?: unknown;
}

function permissionRecords(value: unknown): PermissionRecord[] {
  if (!value || typeof value !== "object") return [];
  const permissions = (value as { permissions?: unknown }).permissions;
  return Array.isArray(permissions)
    ? permissions.filter((item): item is PermissionRecord =>
        Boolean(item && typeof item === "object"),
      )
    : [];
}

/**
 * Security is the authority for tenant decision controls. Unknown or legacy
 * permission shapes fail closed so a missing response never enables approval.
 */
export function hasDecisionApprovalPermission(value: unknown): boolean {
  return permissionRecords(value).some(
    (permission) =>
      (permission.domain === "decisions" ||
        permission.domain === "intelligence") &&
      permission.action === "approve",
  );
}
