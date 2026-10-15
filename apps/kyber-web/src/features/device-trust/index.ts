export {
  useDeviceList,
  useDeviceAdmin,
  useDeviceEnrolment,
  useDeviceProof,
} from './use-device-trust';
export type {
  DeviceListState,
  DeviceAdminState,
  DeviceEnrolmentState,
  DeviceProofState,
  EnrolmentState,
  ProofKeyState,
} from './use-device-trust';

export {
  fetchDevices,
  fetchRegistrationOptions,
  verifyRegistration,
  requestProofChallenge,
  verifyProof,
  approveDevice,
  suspendDevice,
  revokeDevice,
  renameDevice,
} from './device-client';
export type { RegistrationOptionsInput, RegistrationVerifyInput, ProofVerifyInput } from './device-client';

export {
  generateProofKey,
  loadProofKey,
  ensureProofKey,
  clearProofKey,
  exportPublicKeySpki,
  signProofChallenge,
  isProofKeySupported,
  ProofKeyUnsupportedError,
  PROOF_KEY_ALGORITHM,
  PROOF_KEY_SIGN_PARAMS,
} from './proof-key';
export type { DeviceProofKeyRecord } from './proof-key';

export {
  isWebAuthnSupported,
  performRegistration,
  toCreationOptions,
  describeUserAgent,
  WebAuthnUnsupportedError,
  WebAuthnCancelledError,
} from './webauthn';
export type { WebAuthnAttestationPayload } from './webauthn';

export { idbGet, idbPut, idbDelete, isIndexedDbAvailable, DEVICE_TRUST_DB } from './idb';
