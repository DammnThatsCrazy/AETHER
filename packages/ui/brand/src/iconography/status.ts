import type { IconDescriptor } from './types';

export type CapabilityStatus =
  | 'disabled' | 'disabled_intentionally' | 'not_in_release' | 'not_entitled' | 'unavailable' | 'externally_blocked'
  | 'not_configured' | 'credential_required' | 'credential_invalid' | 'connection_testing' | 'credential_waiting' | 'provisioning'
  | 'replay_validated' | 'sandbox_validated' | 'partner_live' | 'live' | 'degraded' | 'stale' | 'partial' | 'error' | 'kill_switch_active';

export interface StatusDescriptor extends IconDescriptor {
  readonly tone: 'neutral' | 'action' | 'progress' | 'validating' | 'live' | 'caution' | 'critical';
  readonly notLive: boolean;
}

/** Mirrors the existing capability-state truth model; this mapping changes presentation only. */
export const statusIcons = {
  disabled: { icon: 'circle-off', label: 'Disabled', decorativeByDefault: true, description: 'Turned off by an operator or compliance hold.', tone: 'neutral', notLive: true },
  disabled_intentionally: { icon: 'ban', label: 'Disabled intentionally', decorativeByDefault: true, description: 'Deliberately omitted by product or release policy.', tone: 'neutral', notLive: true },
  not_in_release: { icon: 'package-x', label: 'Not in release', decorativeByDefault: true, description: 'Not shipped in the active release class.', tone: 'neutral', notLive: true },
  not_entitled: { icon: 'lock-keyhole', label: 'Not entitled', decorativeByDefault: true, description: 'Not included in the active entitlement.', tone: 'neutral', notLive: true },
  unavailable: { icon: 'circle-help', label: 'Unavailable', decorativeByDefault: true, description: 'Capability availability could not be established.', tone: 'critical', notLive: true },
  externally_blocked: { icon: 'circle-stop', label: 'Externally blocked', decorativeByDefault: true, description: 'An external provider or approval blocks progress.', tone: 'action', notLive: true },
  not_configured: { icon: 'sliders-horizontal', label: 'Not configured', decorativeByDefault: true, description: 'Configuration or credentials are absent.', tone: 'neutral', notLive: true },
  credential_required: { icon: 'key-round', label: 'Credential required', decorativeByDefault: true, description: 'Configuration exists but credentials are needed.', tone: 'action', notLive: true },
  credential_invalid: { icon: 'key-x', label: 'Credential invalid', decorativeByDefault: true, description: 'Provider rejected the credential.', tone: 'critical', notLive: true },
  connection_testing: { icon: 'loader-circle', label: 'Testing connection', decorativeByDefault: true, description: 'Provider connection is being probed.', tone: 'progress', notLive: true },
  credential_waiting: { icon: 'clock-3', label: 'Awaiting activation', decorativeByDefault: true, description: 'Credentials were accepted; activation is pending.', tone: 'progress', notLive: true },
  provisioning: { icon: 'boxes', label: 'Provisioning', decorativeByDefault: true, description: 'Provider resources are being created.', tone: 'progress', notLive: true },
  replay_validated: { icon: 'history', label: 'Replay validated', decorativeByDefault: true, description: 'Validated against replayed provider traffic, not live.', tone: 'validating', notLive: true },
  sandbox_validated: { icon: 'flask-conical', label: 'Sandbox validated', decorativeByDefault: true, description: 'Validated in a provider sandbox, not production.', tone: 'validating', notLive: true },
  partner_live: { icon: 'circle-check-big', label: 'Partner live', decorativeByDefault: true, description: 'Live against the production provider.', tone: 'live', notLive: false },
  live: { icon: 'badge-check', label: 'Live', decorativeByDefault: true, description: 'Live against the production provider.', tone: 'live', notLive: false },
  degraded: { icon: 'triangle-alert', label: 'Degraded', decorativeByDefault: true, description: 'A dependency failed; data may be reduced.', tone: 'critical', notLive: false },
  stale: { icon: 'clock-alert', label: 'Stale', decorativeByDefault: true, description: 'Data is older than its freshness SLA.', tone: 'caution', notLive: false },
  partial: { icon: 'pie-chart', label: 'Partial', decorativeByDefault: true, description: 'Some expected inputs are absent.', tone: 'caution', notLive: false },
  error: { icon: 'circle-alert', label: 'Error', decorativeByDefault: true, description: 'The capability read failed.', tone: 'critical', notLive: false },
  kill_switch_active: { icon: 'octagon-x', label: 'Kill switch active', decorativeByDefault: true, description: 'Capability is halted by an active kill switch.', tone: 'critical', notLive: true },
} as const satisfies Readonly<Record<CapabilityStatus, StatusDescriptor>>;
