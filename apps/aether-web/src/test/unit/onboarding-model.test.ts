import { describe, expect, it } from 'vitest';
import { SDK_VERSION } from '@aether/shared';
import type { ActivationStatus } from '@aether-app/features/activation/use-activation';
import {
  authenticationLabel,
  canRecordSdkSelection,
  deriveResumeStep,
  isRestartRequested,
  keyMintRoute,
  platformsFor,
  sdkIdsForPlatforms,
  sdkKeyLabel,
  sourceRowState,
  stageStatuses,
  workspaceSlug,
  SDK_OPTIONS,
} from '@aether-app/pages/onboarding/onboarding-model';

function status(patch: Partial<ActivationStatus>): ActivationStatus {
  return {
    state: 'account_verified',
    selected_plan_tier: null,
    sdk_selection: [],
    created_key_ids: [],
    billing_state: 'billing_pending',
    first_value_evidence: {},
    waiting_reason: null,
    intents: [],
    history: [],
    ...patch,
  };
}

describe('deriveResumeStep', () => {
  it('starts a fresh tenant on Workspace', () => {
    expect(deriveResumeStep(status({}), false)).toBe(1);
    expect(deriveResumeStep(null, false)).toBe(1);
  });

  it('resumes from durable server state', () => {
    expect(deriveResumeStep(status({ intents: ['grow_revenue'] }), false)).toBe(2);
    expect(deriveResumeStep(status({ intents: ['grow_revenue'], sdk_selection: ['web'], state: 'sdk_selected' }), false)).toBe(3);
    expect(deriveResumeStep(status({ created_key_ids: ['k1'], state: 'waiting_for_event' }), false)).toBe(4);
    expect(deriveResumeStep(status({ state: 'complete' }), false)).toBe(4);
  });

  it('always restarts at step 1 for the tester walk-through', () => {
    expect(deriveResumeStep(status({ state: 'complete', created_key_ids: ['k1'] }), true)).toBe(1);
  });
});

describe('workspaceSlug', () => {
  it('lowercases, hyphenates and trims', () => {
    expect(workspaceSlug('Northpeak Outdoor Co.')).toBe('northpeak-outdoor-co');
    expect(workspaceSlug('  --  ')).toBe('workspace');
    expect(workspaceSlug('a'.repeat(80)).length).toBeLessThanOrEqual(63);
  });
});

describe('keyMintRoute', () => {
  it('follows the activation state machine guards', () => {
    expect(keyMintRoute('account_verified')).toBe('needs_plan');
    expect(keyMintRoute('billing_pending')).toBe('select_then_activation');
    expect(keyMintRoute('sdk_selected')).toBe('activation');
    expect(keyMintRoute('waiting_for_event')).toBe('activation');
    expect(keyMintRoute('event_received')).toBe('tenant_api_keys');
    expect(keyMintRoute('complete')).toBe('tenant_api_keys');
    expect(keyMintRoute('blocked')).toBe('blocked');
  });

  it('only re-records SDK selection where the backend allows it', () => {
    expect(canRecordSdkSelection('billing_active')).toBe(true);
    expect(canRecordSdkSelection('sdk_selected')).toBe(true);
    expect(canRecordSdkSelection('waiting_for_event')).toBe(false);
  });
});

describe('SDK fleet helpers', () => {
  it('maps SDK choices onto distinct backend platforms (React shares the web platform)', () => {
    expect(platformsFor(['web', 'react', 'ios'])).toEqual(['web', 'ios']);
    expect(platformsFor(['react'])).toEqual(['web']);
  });

  it('restores selections from recorded platforms without inventing React', () => {
    expect(sdkIdsForPlatforms(['web', 'android'])).toEqual(['web', 'android']);
  });

  it('uses the canonical native install coordinates and shared SDK version', () => {
    const android = SDK_OPTIONS.find(sdk => sdk.id === 'android')?.snippet ?? '';
    const ios = SDK_OPTIONS.find(sdk => sdk.id === 'ios')?.snippet ?? '';
    expect(android).toContain(`implementation("io.aether:sdk-android:${SDK_VERSION}")`);
    expect(ios).toContain(`pod 'AetherSDK', '= ${SDK_VERSION}'`);
  });

  it('gives every SDK its own key label', () => {
    const labels = SDK_OPTIONS.map(sdkKeyLabel);
    expect(new Set(labels).size).toBe(SDK_OPTIONS.length);
  });
});

describe('sourceRowState', () => {
  it('projects connect states onto row states', () => {
    expect(sourceRowState({ connectable: true, connection_state: 'available' })).toBe('available');
    expect(sourceRowState({ connectable: true, connection_state: 'credential_waiting' })).toBe('in_progress');
    expect(sourceRowState({ connectable: true, connection_state: 'initial_sync_running' })).toBe('syncing');
    expect(sourceRowState({ connectable: true, connection_state: 'connected' })).toBe('connected');
    expect(sourceRowState({ connectable: true, connection_state: 'sync_failed' })).toBe('attention');
    expect(sourceRowState({ connectable: false, connection_state: 'available' })).toBe('unavailable');
  });

  it('labels authentication methods', () => {
    expect(authenticationLabel('oauth2')).toBe('OAuth');
    expect(authenticationLabel('api_key')).toBe('API key');
    expect(authenticationLabel('webhook_hmac')).toBe('Signed webhook');
  });
});

describe('stageStatuses', () => {
  it('marks only the first unfinished stage as running', () => {
    expect(
      stageStatuses([
        { name: 'events_received', status: 'passed' },
        { name: 'identity_resolution_verified', status: 'pending' },
        { name: 'profile360_verified', status: 'pending' },
      ]),
    ).toEqual(['passed', 'running', 'waiting', 'waiting', 'waiting']);
  });

  it('surfaces failures and treats not_applicable as done', () => {
    expect(
      stageStatuses([
        { name: 'events_received', status: 'passed' },
        { name: 'identity_resolution_verified', status: 'not_applicable' },
        { name: 'profile360_verified', status: 'failed' },
      ]),
    ).toEqual(['passed', 'not_applicable', 'failed', 'waiting', 'waiting']);
  });

  it('is all waiting-but-first when nothing has been recorded', () => {
    expect(stageStatuses(null)).toEqual(['running', 'waiting', 'waiting', 'waiting', 'waiting']);
  });
});

describe('isRestartRequested', () => {
  it('honours the tester entry outside production only', () => {
    expect(isRestartRequested('?onboarding=restart', 'staging')).toBe(true);
    expect(isRestartRequested('?onboarding=restart', 'local')).toBe(true);
    expect(isRestartRequested('?onboarding=restart', 'production')).toBe(false);
    expect(isRestartRequested('?other=1', 'staging')).toBe(false);
  });
});
