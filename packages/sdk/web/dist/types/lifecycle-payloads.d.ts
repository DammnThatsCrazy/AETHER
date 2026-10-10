/** Common fields present on all x402 lifecycle payloads */
export interface X402BasePayload {
    tenant_id: string;
    agent_id: string;
    beneficiary_actor_id?: string;
    resource_id?: string;
    service_id?: string;
    provider?: string;
    protocol?: string;
    amount?: string | number;
    currency?: string;
    capability_requested?: string;
    authorization_id?: string;
    payment_intent_id?: string;
    settlement_event_id?: string;
    facilitator_id?: string;
    receipt_id?: string;
    execution_id?: string;
    outcome_id?: string;
    status?: string;
    failure_reason?: string;
    timestamp?: string;
    metadata?: Record<string, unknown>;
}
export interface X402ResourceRequestedPayload extends X402BasePayload {
    resource_id: string;
    service_id: string;
}
export interface X402PaymentRequiredPayload extends X402BasePayload {
    amount: string | number;
    currency: string;
    service_id: string;
}
export interface X402QuoteReceivedPayload extends X402BasePayload {
    payment_intent_id: string;
    amount: string | number;
    currency: string;
}
export interface X402AuthorizationRequestedPayload extends X402BasePayload {
    authorization_id: string;
    payment_intent_id: string;
}
export interface X402AuthorizationResolvedPayload extends X402BasePayload {
    authorization_id: string;
    payment_intent_id: string;
    status: 'authorized' | 'denied';
}
export interface X402PaymentIntentCreatedPayload extends X402BasePayload {
    payment_intent_id: string;
    amount: string | number;
    currency: string;
}
export interface X402PaymentSubmittedPayload extends X402BasePayload {
    payment_intent_id: string;
    settlement_event_id: string;
}
export interface X402PaymentSettledPayload extends X402BasePayload {
    payment_intent_id: string;
    settlement_event_id: string;
    amount: string | number;
    currency: string;
}
export interface X402PaymentFailedPayload extends X402BasePayload {
    payment_intent_id: string;
    settlement_event_id?: string;
    failure_reason: string;
}
export interface X402PaymentTimeoutPayload extends X402BasePayload {
    payment_intent_id: string;
    settlement_event_id?: string;
}
export interface X402ReceiptVerifiedPayload extends X402BasePayload {
    receipt_id: string;
    settlement_event_id: string;
}
export interface X402AccessGrantedPayload extends X402BasePayload {
    resource_id: string;
    payment_intent_id: string;
    execution_id?: string;
}
export interface X402AccessDeniedPayload extends X402BasePayload {
    resource_id: string;
    failure_reason: string;
}
export interface X402RefundOrReversalPayload extends X402BasePayload {
    settlement_event_id: string;
    payment_intent_id: string;
    amount: string | number;
    currency: string;
}
/** Common fields present on all agent lifecycle payloads */
export interface AgentBasePayload {
    tenant_id: string;
    agent_id: string;
    owner_user_id?: string;
    owner_org_id?: string;
    beneficiary_actor_id?: string;
    parent_agent_id?: string;
    root_agent_id?: string;
    task_id?: string;
    parent_task_id?: string;
    subtask_ids?: string[];
    delegation_id?: string;
    authorization_id?: string;
    capability?: string;
    tool_id?: string;
    resource_id?: string;
    policy_id?: string;
    decision?: string;
    outcome_id?: string;
    status?: string;
    failure_reason?: string;
    timestamp?: string;
    metadata?: Record<string, unknown>;
}
export interface AgentRegisteredPayload extends AgentBasePayload {
    owner_user_id: string;
}
export interface AgentUpdatedPayload extends AgentBasePayload {
}
export interface AgentAuthorizedPayload extends AgentBasePayload {
    authorization_id: string;
}
export interface AgentCapabilityGrantedPayload extends AgentBasePayload {
    capability: string;
    authorization_id?: string;
}
export interface AgentCapabilityRevokedPayload extends AgentBasePayload {
    capability: string;
}
export interface AgentTaskCreatedPayload extends AgentBasePayload {
    task_id: string;
}
export interface AgentTaskDecomposedPayload extends AgentBasePayload {
    task_id: string;
    parent_task_id: string;
    subtask_ids: string[];
}
export interface AgentTaskStartedPayload extends AgentBasePayload {
    task_id: string;
}
export interface AgentTaskCompletedPayload extends AgentBasePayload {
    task_id: string;
    outcome_id?: string;
}
export interface AgentTaskFailedPayload extends AgentBasePayload {
    task_id: string;
    failure_reason: string;
}
export interface AgentToolCalledPayload extends AgentBasePayload {
    tool_id: string;
    task_id?: string;
}
export interface AgentResourceRequestedPayload extends AgentBasePayload {
    resource_id: string;
    task_id?: string;
}
export interface AgentDelegatedTaskPayload extends AgentBasePayload {
    delegation_id: string;
    task_id: string;
    parent_agent_id: string;
}
export interface AgentSubagentSpawnedPayload extends AgentBasePayload {
    parent_agent_id: string;
    root_agent_id: string;
    task_id?: string;
    delegation_id?: string;
}
export interface AgentPolicyEvaluatedPayload extends AgentBasePayload {
    policy_id: string;
    decision: string;
    task_id?: string;
}
export interface AgentHandoffPayload extends AgentBasePayload {
    task_id?: string;
}
export interface AgentEscalatedToHumanPayload extends AgentBasePayload {
    task_id?: string;
    failure_reason?: string;
}
export interface AgentOutcomeRecordedPayload extends AgentBasePayload {
    outcome_id: string;
    task_id?: string;
}
