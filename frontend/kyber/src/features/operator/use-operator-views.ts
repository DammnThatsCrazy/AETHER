/**
 * Layer 3 — Operator view hooks.
 *
 * Each hook composes multiple Layer 1 query hooks and Layer 2 mutation hooks
 * for a specific Kyber operator workflow. No direct API calls at this level.
 */

import { useAgentStatus, useAgentAudit, useAgentGraph, useAgentTrust, useAgentTask, useSubmitTask, useKillSwitch } from '@kyber/features/agent/use-agent';
import { useResolveError, useSuppressError } from '@kyber/features/diagnostics/use-diagnostics-mutations';
import { useDiagnosticsData } from '@kyber/features/diagnostics/use-diagnostics-data';
import { useResolutionPending, useResolutionConfig, useApproveResolution, useRejectResolution, useRunResolutionBatch, useUpdateResolutionConfig } from '@kyber/features/resolution/use-resolution';
import { useMergeIdentityProfiles } from '@kyber/features/identity/use-identity';
import { useEntityCluster, useWalletRisk, useWalletProfile } from '@kyber/features/intelligence/use-intelligence';
import { useGraphEntity, useGraphCluster, useGraphFusionProfile, useGraphFusionExposure, useGraphLinks, useGraphDelegations, useGraphHighConfidenceLinks, useGraphSearchEntities, useValidateDelegation } from '@kyber/features/graph/use-graph';
import { useBehavioralEntity, useExpectationsExplain, useExpectationsEntity, useExpectationsContradictions, useScanBehavior, useScanExpectations, useBehavioralSummary } from '@kyber/features/behavioral/use-behavioral';
import { useBehaviorLatest } from '@kyber/features/behavior/use-behavior';
import { useCrossdomainAccounts, useCrossdomainFusionProfile, useEntityComplianceActions, useEntityCrossdomainEvents, useCrossdomainLinks, useCrossdomainFusionExposure, useRegisterAccount, useRecordOrder, useRecordExecution, useCreateCrossdomainLink } from '@kyber/features/crossdomain/use-crossdomain';
import { useFraudStats, useFraudConfig, useEvaluateFraud, useEvaluateFraudBatch, useUpdateFraudConfig } from '@kyber/features/fraud/use-fraud';
import { useProfile360 } from '@kyber/features/profile360/use-profile360';
import { useGrantDelegation, useRevokeDelegation, useValidateDelegationAction } from '@kyber/features/delegation/use-delegation';
import { useChains, useProtocols, useTokens, useWeb3Coverage, useUnclassifiedContracts, useRegisterChain, useRegisterProtocol, useRegisterToken, useRegisterContract, useReclassifyContract, useClassifyContract, useBatchObservations } from '@kyber/features/web3/use-web3';
import { useOracleProofStatus, useGenerateProof, useVerifyProof } from '@kyber/features/oracle/use-oracle';
import { useAttributionModels, useAttributionJourney, useResolveAttribution, useRecordAttributionTouchpoint, useClearAttributionJourney } from '@kyber/features/attribution/use-attribution';
import { useCampaign, useCampaignsList, useCampaignAttribution, useUpdateCampaign, useDeleteCampaign, useRecordCampaignTouchpoint } from '@kyber/features/campaigns/use-campaigns';
import { useAutomationMetrics, useAutomationInsights } from '@kyber/features/automation/use-automation';
import { useMLModels, useMLFeatures, useMLPredict, useMLPredictBatch } from '@kyber/features/ml/use-ml';
import { useTenant, useApiKeys, useBillingInfo, useBillingUsage, useBillingInvoices, useCreateTenant, useUpdateTenant, useCreateApiKey, useRevokeApiKey, useCreateCheckoutSession, useCreatePortalSession } from '@kyber/features/admin/use-admin';
import { useRWAAsset, useRWAHolders, useRWACashflows, useRWAPolicies, useRWAExposure, useRWAReserveCredibility, useCreateRWAAsset, useCreateRWAPolicy, useSimulateRWATransfer, useRecordRWACashflow, useRegisterRWAHolder } from '@kyber/features/rwa/use-rwa';
import { useAgentActions, useRPCHealth, useOnchainContract, useRecordOnchainAction, useConfigureListener } from '@kyber/features/onchain/use-onchain';
import { useX402AgentHistory, useSnapshotX402Graph } from '@kyber/features/x402/use-x402';
import { useLakeStatus, useLakeQuality, useLakeAudit, useLakeIngest, useLakeRollback, useLakeMaterialize } from '@kyber/features/lake/use-lake';
import { useAlerts, useWebhooks, useCreateAlert, useCreateWebhook, useDeleteWebhook } from '@kyber/features/notifications/use-notifications';
import { useFeesReport, useAgentSpend, useRecordPayment, useRecordHire } from '@kyber/features/commerce/use-commerce-ops';
import { useDsrRequests, useCompleteDsr } from '@kyber/features/consent/use-consent';
import { useRewardsCampaigns, useRewardsQueueStats, useProcessRewardsQueue, useCreateRewardsCampaign, useEvaluateRewards } from '@kyber/features/rewards/use-rewards';
import { usePopulationSummary, usePopulationGroups } from '@kyber/features/population/use-population';

// ── Agent Dispatch ─────────────────────────────────────────────────────────────

/** Aggregates everything an operator needs to dispatch agents and manage delegation. */
export function useAgentDispatchView() {
  const status = useAgentStatus();
  const audit = useAgentAudit();
  const submitTask = useSubmitTask();
  const killSwitch = useKillSwitch();
  const grantDelegation = useGrantDelegation();
  const revokeDelegation = useRevokeDelegation();
  const validateDelegation = useValidateDelegationAction();
  return { status, audit, submitTask, killSwitch, grantDelegation, revokeDelegation, validateDelegation };
}

// ── System Health ─────────────────────────────────────────────────────────────

/** System health view — diagnostics + circuit breakers + agent status + error mutations. */
export function useSystemHealthView() {
  const diagnostics = useDiagnosticsData();
  const agentStatus = useAgentStatus();
  const resolveError = useResolveError();
  const suppressError = useSuppressError();
  const killSwitch = useKillSwitch();
  return { diagnostics, agentStatus, resolveError, suppressError, killSwitch };
}

// ── Entity Ops ────────────────────────────────────────────────────────────────

/** Full entity operator view — identity, graph, behavioral, crossdomain. */
export function useEntityOpsView(entityId: string) {
  const profile360 = useProfile360('customer', entityId);
  const cluster = useEntityCluster(entityId);
  const graph = useGraphEntity(entityId);
  const fusionProfile = useGraphFusionProfile(entityId);
  const fusionExposure = useGraphFusionExposure(entityId);
  const links = useGraphLinks(entityId);
  const behavioral = useBehavioralEntity(entityId);
  const explain = useExpectationsExplain(entityId);
  const crossdomainLinks = useCrossdomainLinks(entityId);
  const crossdomainExposure = useCrossdomainFusionExposure(entityId);
  const scanBehavior = useScanBehavior();
  const scanExpectations = useScanExpectations();
  const mergeProfiles = useMergeIdentityProfiles();
  return {
    profile360, cluster, graph, fusionProfile, fusionExposure, links,
    behavioral, explain, crossdomainLinks, crossdomainExposure,
    scanBehavior, scanExpectations, mergeProfiles,
  };
}

// ── Resolution ────────────────────────────────────────────────────────────────

/** Resolution operator view — pending queue + config + approve/reject/batch. */
export function useResolutionView() {
  const pending = useResolutionPending();
  const config = useResolutionConfig();
  const approve = useApproveResolution();
  const reject = useRejectResolution();
  const runBatch = useRunResolutionBatch();
  const updateConfig = useUpdateResolutionConfig();
  return { pending, config, approve, reject, runBatch, updateConfig };
}

// ── Fraud Ops ─────────────────────────────────────────────────────────────────

/** Fraud ops view — stats + config + evaluate + update. */
export function useFraudOpsView() {
  const stats = useFraudStats();
  const config = useFraudConfig();
  const evaluate = useEvaluateFraud();
  const evaluateBatch = useEvaluateFraudBatch();
  const updateConfig = useUpdateFraudConfig();
  return { stats, config, evaluate, evaluateBatch, updateConfig };
}

// ── Entity Search ─────────────────────────────────────────────────────────────

/** Entity search view — global search across all tenants. */
export function useEntitySearchView(query: string) {
  const results = useGraphSearchEntities(query);
  return { results };
}

// ── Web3 Registry ─────────────────────────────────────────────────────────────

/** Web3 registry view — chain/protocol/token coverage + unclassified + mutations. */
export function useWeb3RegistryView() {
  const chains = useChains();
  const protocols = useProtocols();
  const tokens = useTokens();
  const coverage = useWeb3Coverage();
  const unclassified = useUnclassifiedContracts();
  const registerChain = useRegisterChain();
  const registerProtocol = useRegisterProtocol();
  const registerToken = useRegisterToken();
  const registerContract = useRegisterContract();
  const reclassifyContract = useReclassifyContract();
  const classifyContract = useClassifyContract();
  const batchObservations = useBatchObservations();
  return {
    chains, protocols, tokens, coverage, unclassified,
    registerChain, registerProtocol, registerToken,
    registerContract, reclassifyContract, classifyContract, batchObservations,
  };
}

// ── Oracle ────────────────────────────────────────────────────────────────────

/** Oracle operator view — proof status + generate + verify. */
export function useOracleView(proofId: string) {
  const status = useOracleProofStatus(proofId);
  const generate = useGenerateProof();
  const verify = useVerifyProof();
  return { status, generate, verify };
}

// ── Attribution ───────────────────────────────────────────────────────────────

/** Attribution view — campaign + models + journey + mutations. */
export function useAttributionView(campaignId: string, userId = '') {
  const campaign = useCampaign(campaignId);
  const models = useAttributionModels();
  const campaignAttribution = useCampaignAttribution(campaignId);
  const journey = useAttributionJourney(userId);
  const resolve = useResolveAttribution();
  const recordTouchpoint = useRecordAttributionTouchpoint();
  const clearJourney = useClearAttributionJourney();
  return { campaign, models, campaignAttribution, journey, resolve, recordTouchpoint, clearJourney };
}

// ── Behavioral ────────────────────────────────────────────────────────────────

/** Behavioral operator view — signals + expectations + contradictions + scan mutations. */
export function useBehavioralView(entityId: string) {
  const behavioral = useBehavioralEntity(entityId);
  const explain = useExpectationsExplain(entityId);
  const entityExpectations = useExpectationsEntity(entityId);
  const contradictions = useExpectationsContradictions();
  const behaviorSnap = useBehaviorLatest(entityId);
  const scanBehavior = useScanBehavior();
  const scanExpectations = useScanExpectations();
  return { behavioral, explain, entityExpectations, contradictions, behaviorSnap, scanBehavior, scanExpectations };
}

// ── RWA Ops ───────────────────────────────────────────────────────────────────

/** RWA operator view — asset data + holders + cashflows + policies + mutations. */
export function useRWAOpsView(assetId: string, entityId = '') {
  const asset = useRWAAsset(assetId);
  const holders = useRWAHolders(assetId);
  const cashflows = useRWACashflows(assetId);
  const policies = useRWAPolicies(assetId);
  const reserve = useRWAReserveCredibility(assetId);
  const exposure = useRWAExposure(entityId);
  const createAsset = useCreateRWAAsset();
  const createPolicy = useCreateRWAPolicy();
  const simulate = useSimulateRWATransfer();
  const recordCashflow = useRecordRWACashflow();
  const registerHolder = useRegisterRWAHolder();
  return { asset, holders, cashflows, policies, reserve, exposure, createAsset, createPolicy, simulate, recordCashflow, registerHolder };
}

// ── ML Ops ────────────────────────────────────────────────────────────────────

/** ML operator view — models + features + predict mutations. */
export function useMLOpsView(entityId: string) {
  const models = useMLModels();
  const features = useMLFeatures(entityId);
  const predict = useMLPredict();
  const predictBatch = useMLPredictBatch();
  return { models, features, predict, predictBatch };
}

// ── Tenant Admin ──────────────────────────────────────────────────────────────

/** Tenant admin view — tenant + API keys + billing + mutations. */
export function useTenantAdminView(tenantId: string) {
  const tenant = useTenant(tenantId);
  const apiKeys = useApiKeys(tenantId);
  const billingInfo = useBillingInfo(tenantId);
  const billingUsage = useBillingUsage(tenantId);
  const invoices = useBillingInvoices(tenantId);
  const createTenant = useCreateTenant();
  const updateTenant = useUpdateTenant();
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();
  const createCheckout = useCreateCheckoutSession();
  const createPortal = useCreatePortalSession();
  return { tenant, apiKeys, billingInfo, billingUsage, invoices, createTenant, updateTenant, createApiKey, revokeApiKey, createCheckout, createPortal };
}

// ── Crossdomain Entity ────────────────────────────────────────────────────────

/** Crossdomain entity view — accounts + events + compliance + fusion + mutations. */
export function useCrossdomainEntityView(entityId: string) {
  const accounts = useCrossdomainAccounts({ owner: entityId });
  const events = useEntityCrossdomainEvents(entityId);
  const compliance = useEntityComplianceActions(entityId);
  const fusion = useCrossdomainFusionProfile(entityId);
  const links = useCrossdomainLinks(entityId);
  const registerAccount = useRegisterAccount();
  const recordOrder = useRecordOrder();
  const recordExecution = useRecordExecution();
  const createLink = useCreateCrossdomainLink();
  return { accounts, events, compliance, fusion, links, registerAccount, recordOrder, recordExecution, createLink };
}

// ── Onchain Ops ───────────────────────────────────────────────────────────────

/** Onchain operator view — actions + RPC health + x402 history + mutations. */
export function useOnchainOpsView(agentId: string) {
  const actions = useAgentActions(agentId);
  const rpcHealth = useRPCHealth();
  const x402History = useX402AgentHistory(agentId);
  const recordAction = useRecordOnchainAction();
  const configureListener = useConfigureListener();
  const snapshotGraph = useSnapshotX402Graph();
  return { actions, rpcHealth, x402History, recordAction, configureListener, snapshotGraph };
}

// ── Lake Ops ──────────────────────────────────────────────────────────────────

/** Lake operator view — quality + status + audit + ingest/rollback/materialize. */
export function useLakeOpsView(domain: string, sourceTag = '') {
  const status = useLakeStatus();
  const quality = useLakeQuality(domain);
  const audit = useLakeAudit(domain, sourceTag);
  const ingest = useLakeIngest();
  const rollback = useLakeRollback();
  const materialize = useLakeMaterialize();
  return { status, quality, audit, ingest, rollback, materialize };
}

// ── Notifications ─────────────────────────────────────────────────────────────

/** Notifications view — alerts + webhooks + mutations. */
export function useNotificationsView() {
  const alerts = useAlerts();
  const webhooks = useWebhooks();
  const createAlert = useCreateAlert();
  const createWebhook = useCreateWebhook();
  const deleteWebhook = useDeleteWebhook();
  return { alerts, webhooks, createAlert, createWebhook, deleteWebhook };
}

// ── Commerce Ops ──────────────────────────────────────────────────────────────

/** Commerce operator view — fees report + agent spend + record mutations. */
export function useCommerceOpsView(agentId = '', period?: string) {
  const feesReport = useFeesReport(period);
  const agentSpend = useAgentSpend(agentId);
  const recordPayment = useRecordPayment();
  const recordHire = useRecordHire();
  return { feesReport, agentSpend, recordPayment, recordHire };
}

// ── Campaign Ops ──────────────────────────────────────────────────────────────

/** Campaign operator view — campaign detail + automation metrics + attribution + mutations. */
export function useCampaignOpsView(campaignId: string) {
  const campaign = useCampaign(campaignId);
  const campaigns = useCampaignsList();
  const automationMetrics = useAutomationMetrics(campaignId);
  const insights = useAutomationInsights();
  const campaignAttribution = useCampaignAttribution(campaignId);
  const updateCampaign = useUpdateCampaign();
  const deleteCampaign = useDeleteCampaign();
  const recordTouchpoint = useRecordCampaignTouchpoint();
  return { campaign, campaigns, automationMetrics, insights, campaignAttribution, updateCampaign, deleteCampaign, recordTouchpoint };
}

// ── Consent DSR ───────────────────────────────────────────────────────────────

/** Consent DSR view — DSR queue + completeDsr mutation. */
export function useConsentDsrView(params?: { status?: string; limit?: number }) {
  const requests = useDsrRequests(params);
  const complete = useCompleteDsr();
  return { requests, complete };
}

// ── Rewards Ops ───────────────────────────────────────────────────────────────

/** Rewards operator view — campaigns + queue stats + mutations. */
export function useRewardsOpsView() {
  const campaigns = useRewardsCampaigns();
  const queueStats = useRewardsQueueStats();
  const processQueue = useProcessRewardsQueue();
  const createCampaign = useCreateRewardsCampaign();
  const evaluate = useEvaluateRewards();
  return { campaigns, queueStats, processQueue, createCampaign, evaluate };
}

// ── Population ────────────────────────────────────────────────────────────────

/** Population view — summary + groups by type. */
export function usePopulationView(type?: string) {
  const summary = usePopulationSummary();
  const groups = usePopulationGroups(type);
  return { summary, groups };
}
