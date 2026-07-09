import { describe, expect, it } from 'vitest';
import { EVENT_CONSENT_PURPOSE, EVENT_FAMILY, type EventType } from './events';
import { SDK_INGESTION_PATH, SDK_VERSION } from './sdk-version';

// ---------------------------------------------------------------------------
// Build the full set of EventType values from the EVENT_FAMILY record
// (which is typed as Record<EventType, EventFamily>, so its keys are exhaustive)
// ---------------------------------------------------------------------------
const allEventTypes = Object.keys(EVENT_FAMILY) as EventType[];

describe('events-registry', () => {
  // ---------------------------------------------------------------------------
  // EVENT_CONSENT_PURPOSE coverage
  // ---------------------------------------------------------------------------

  it('every EventType value has a mapping in EVENT_CONSENT_PURPOSE', () => {
    for (const eventType of allEventTypes) {
      expect(EVENT_CONSENT_PURPOSE).toHaveProperty(eventType);
      expect(EVENT_CONSENT_PURPOSE[eventType]).toBeTruthy();
    }
  });

  // ---------------------------------------------------------------------------
  // EVENT_FAMILY coverage
  // ---------------------------------------------------------------------------

  it('every EventType value has a mapping in EVENT_FAMILY', () => {
    for (const eventType of allEventTypes) {
      expect(EVENT_FAMILY).toHaveProperty(eventType);
      expect(EVENT_FAMILY[eventType]).toBeTruthy();
    }
  });

  // ---------------------------------------------------------------------------
  // Consent event — always allowed (analytics gate, not blocked)
  // ---------------------------------------------------------------------------

  it('consent event is mapped to analytics purpose (always allowed gate)', () => {
    // The consent event uses the analytics purpose, which the event queue
    // treats as always-pass so consent signals are never blocked.
    const purpose = EVENT_CONSENT_PURPOSE['consent'];
    expect(['analytics', null, undefined]).toContain(purpose);
  });

  // ---------------------------------------------------------------------------
  // SDK transport contract
  // ---------------------------------------------------------------------------

  it('SDK_INGESTION_PATH is /v1/batch', () => {
    expect(SDK_INGESTION_PATH).toBe('/v1/batch');
  });

  it('SDK_VERSION is 8.12.0', () => {
    expect(SDK_VERSION).toBe('8.12.0');
  });

  // ---------------------------------------------------------------------------
  // Invalid type rejection
  // ---------------------------------------------------------------------------

  it('a known invalid type string is not in the EventType values', () => {
    const invalidType = 'not_a_real_event_type_xyz';
    expect(allEventTypes).not.toContain(invalidType);
  });

  // ---------------------------------------------------------------------------
  // Spot-checks for key event families
  // ---------------------------------------------------------------------------

  it('journey events are in the journey family', () => {
    const journeyTypes: EventType[] = [
      'journey_started', 'journey_paused', 'journey_resumed',
      'journey_continued', 'journey_completed', 'journey_abandoned',
      'journey_checkpoint',
    ];
    for (const t of journeyTypes) {
      expect(EVENT_FAMILY[t]).toBe('journey');
    }
  });

  it('agent lifecycle events are in the agent family', () => {
    const agentTypes: EventType[] = [
      'agent_registered', 'agent_updated', 'agent_authorized',
      'agent_deauthorized', 'agent_capability_granted', 'agent_capability_revoked',
      'agent_task_created', 'agent_task_decomposed', 'agent_task_started',
      'agent_task_completed', 'agent_task_failed', 'agent_tool_called',
      'agent_resource_requested', 'agent_delegated_task', 'agent_subagent_spawned',
      'agent_policy_evaluated', 'agent_handoff', 'agent_escalated_to_human',
      'agent_outcome_recorded',
    ];
    expect(agentTypes).toHaveLength(19);
    for (const t of agentTypes) {
      expect(EVENT_FAMILY[t]).toBe('agent');
    }
  });

  it('x402 lifecycle events are in the x402 family', () => {
    const x402Types: EventType[] = [
      'x402_resource_requested', 'x402_payment_required', 'x402_quote_received',
      'x402_authorization_requested', 'x402_authorization_resolved',
      'x402_payment_intent_created', 'x402_payment_submitted', 'x402_payment_settled',
      'x402_payment_failed', 'x402_payment_timeout', 'x402_receipt_verified',
      'x402_access_granted', 'x402_access_denied', 'x402_refund_or_reversal',
    ];
    expect(x402Types).toHaveLength(14);
    for (const t of x402Types) {
      expect(EVENT_FAMILY[t]).toBe('x402');
    }
  });

  it('reward enablement events are in the reward family', () => {
    const rewardTypes: EventType[] = [
      'reward_action_queued', 'reward_proof_generated',
      'reward_delivered', 'reward_claim_submitted',
    ];
    for (const t of rewardTypes) {
      expect(EVENT_FAMILY[t]).toBe('reward');
    }
  });
});
