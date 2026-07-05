export const STABLECOIN_SCHEMA_VERSION = 'stablecoin.intelligence.v1' as const;

export const stablecoinFinalityStates = ['observed','pending','confirmed','finalized','reverted','dropped','failed','disputed','unknown'] as const;
export type StablecoinFinalityState = typeof stablecoinFinalityStates[number];

export const stablecoinEventTypes = ['transfer','payment','settlement_observation','refund','reversal','mint','burn','redemption','deposit','withdrawal','swap','bridge_deposit','bridge_mint','bridge_burn','bridge_release','liquidity_addition','liquidity_removal','collateral_deposit','collateral_withdrawal','treasury_transfer','reward','fee','agent_requested_payment','x402_challenge_observed','x402_payment_observed','unknown_stablecoin_movement'] as const;
export type StablecoinEventType = typeof stablecoinEventTypes[number];

export const stablecoinCapabilities = ['send','receive','hold','deposit','withdraw','accept_payment','settle','refund','swap','bridge','mint','redeem','collateral','rewards','x402','agent_expenses','treasury','balance_reporting'] as const;
export type StablecoinCapability = typeof stablecoinCapabilities[number];

export const stablecoinSupportStates = ['announced','registered','configured','sandbox_tested','production_tested','observed','production_active','degraded','suspended','deprecated','retired','unsupported','unknown'] as const;
export type StablecoinSupportState = typeof stablecoinSupportStates[number];

export interface StablecoinDeploymentContract { deployment_id: string; canonical_asset_id: string; chain_id: string; network: string; token_standard: string; contract_or_mint: string; decimals: number; deployment_type: string; canonical_or_wrapped: string; issuer_verified: boolean; active: boolean; testnet: boolean; metadata?: Record<string, unknown>; }
export interface StablecoinObservationContract { observation_id: string; tenant_id: string; schema_version: typeof STABLECOIN_SCHEMA_VERSION; source: string; source_record_id: string; source_execution_id: string; source_manifest_id?: string; evidence_id?: string; observed_at: string; chain_id: string; network: string; transaction_hash: string; log_or_instruction_index?: number; finality_status: StablecoinFinalityState; event_type: StablecoinEventType; deployment_id: string; canonical_asset_id: string; amount_atomic: string; amount_decimal?: string; from_address?: string; to_address?: string; classification_confidence?: string; }
