export {
  useCapabilities,
  usePermissions,
  hasCapability,
  hasAnyCapability,
  hasAllCapabilities,
  checkActionClass,
  checkDisclosureLevel,
  LEGACY_GATE_CAPABILITIES,
  LEGACY_GATE_NAMES,
} from './permissions';
export type {
  PermissionCheck,
  CapabilitySnapshot,
  PermissionsSnapshot,
  LegacyGate,
} from './permissions';
export { PermissionGate } from './permission-gate';
export type { PermissionGateProps } from './permission-gate';
