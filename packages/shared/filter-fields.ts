/**
 * DO NOT EDIT — generated from packages/shared/contracts/filter-field-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

import type { FilterOperator } from './graph-contract';

export const filterFieldsContractVersion = '1.0.0' as const;

/** Categories a filterable field can belong to. */
export const filterFieldCategories = [
  'entity',
  'time',
  'geography',
  'device',
  'graph',
  'risk',
  'campaign',
  'economic',
  'truth',
] as const;
export type FilterFieldCategory = typeof filterFieldCategories[number];

/** Value shape of a filterable field. */
export const filterFieldDataTypes = [
  'string',
  'number',
  'boolean',
  'datetime',
  'enum',
  'entity_ref',
  'geography',
] as const;
export type FilterFieldDataType = typeof filterFieldDataTypes[number];

/** Governance sensitivity of a filterable field. */
export const filterFieldSensitivities = [
  'public',
  'tenant_internal',
  'sensitive',
  'restricted',
  'pii',
] as const;
export type FilterFieldSensitivity = typeof filterFieldSensitivities[number];

/** One filterable field: operators are a subset of the canonical FilterOperator union. */
export interface FilterFieldDefinition {
  id: string;
  label: string;
  category: FilterFieldCategory;
  dataType: FilterFieldDataType;
  operators: readonly FilterOperator[];
  sensitivity: FilterFieldSensitivity;
  consentPurpose?: string;
  minimumCohortSize?: number;
}

/** Canonical filter-field registry (sorted by id). */
export const filterFields: readonly FilterFieldDefinition[] = [
  {
    id: 'campaign.attribution_model',
    label: 'Attribution model',
    category: 'campaign',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'marketing',
  },
  {
    id: 'campaign.channel',
    label: 'Campaign channel',
    category: 'campaign',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'marketing',
  },
  {
    id: 'campaign.id',
    label: 'Campaign',
    category: 'campaign',
    dataType: 'entity_ref',
    operators: ['eq', 'neq', 'in', 'not_in', 'exists', 'not_exists'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'marketing',
  },
  {
    id: 'campaign.source',
    label: 'Campaign source',
    category: 'campaign',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'marketing',
  },
  {
    id: 'device.app_version',
    label: 'App version',
    category: 'device',
    dataType: 'string',
    operators: ['eq', 'neq', 'in', 'not_in', 'starts_with'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'device.class',
    label: 'Device class',
    category: 'device',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'device.os',
    label: 'Operating system',
    category: 'device',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'device.platform',
    label: 'Platform',
    category: 'device',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'economic.ltv_usd',
    label: 'Lifetime value (USD)',
    category: 'economic',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'threshold'],
    sensitivity: 'sensitive',
    consentPurpose: 'economic_observability',
  },
  {
    id: 'economic.payment_rail',
    label: 'Payment rail',
    category: 'economic',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'financial_activity',
  },
  {
    id: 'economic.revenue_usd',
    label: 'Revenue (USD)',
    category: 'economic',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'threshold'],
    sensitivity: 'sensitive',
    consentPurpose: 'economic_observability',
  },
  {
    id: 'entity.cluster_id',
    label: 'Identity cluster',
    category: 'entity',
    dataType: 'entity_ref',
    operators: ['eq', 'neq', 'in', 'not_in', 'exists', 'not_exists'],
    sensitivity: 'sensitive',
  },
  {
    id: 'entity.id',
    label: 'Entity ID',
    category: 'entity',
    dataType: 'entity_ref',
    operators: ['eq', 'neq', 'in', 'not_in', 'exists', 'not_exists'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'entity.lifecycle_state',
    label: 'Lifecycle state',
    category: 'entity',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'entity.tags',
    label: 'Tags',
    category: 'entity',
    dataType: 'string',
    operators: ['contains', 'in', 'not_in', 'exists', 'not_exists'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'entity.type',
    label: 'Entity type',
    category: 'entity',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'public',
  },
  {
    id: 'geography.city',
    label: 'City',
    category: 'geography',
    dataType: 'geography',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'location',
    minimumCohortSize: 25,
  },
  {
    id: 'geography.country',
    label: 'Country',
    category: 'geography',
    dataType: 'geography',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'location',
  },
  {
    id: 'geography.region',
    label: 'Region',
    category: 'geography',
    dataType: 'geography',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
    consentPurpose: 'location',
  },
  {
    id: 'graph.depth',
    label: 'Traversal depth',
    category: 'graph',
    dataType: 'number',
    operators: ['eq', 'gt', 'gte', 'lt', 'lte', 'between'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'graph.edge_confidence',
    label: 'Edge confidence',
    category: 'graph',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'threshold'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'graph.edge_type',
    label: 'Edge type',
    category: 'graph',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'graph.relationship_layer',
    label: 'Relationship layer',
    category: 'graph',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'risk.anomaly_score',
    label: 'Anomaly score',
    category: 'risk',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'threshold'],
    sensitivity: 'sensitive',
  },
  {
    id: 'risk.fraud_network_member',
    label: 'Fraud network member',
    category: 'risk',
    dataType: 'boolean',
    operators: ['eq'],
    sensitivity: 'restricted',
  },
  {
    id: 'risk.score',
    label: 'Risk score',
    category: 'risk',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'threshold'],
    sensitivity: 'sensitive',
  },
  {
    id: 'risk.trust_score',
    label: 'Trust score',
    category: 'risk',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'threshold'],
    sensitivity: 'sensitive',
  },
  {
    id: 'time.first_seen',
    label: 'First seen',
    category: 'time',
    dataType: 'datetime',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'relative_time'],
    sensitivity: 'public',
  },
  {
    id: 'time.last_seen',
    label: 'Last seen',
    category: 'time',
    dataType: 'datetime',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'relative_time'],
    sensitivity: 'public',
  },
  {
    id: 'time.occurred_at',
    label: 'Occurred at',
    category: 'time',
    dataType: 'datetime',
    operators: ['gt', 'gte', 'lt', 'lte', 'between', 'relative_time'],
    sensitivity: 'public',
  },
  {
    id: 'truth.confidence_min',
    label: 'Minimum confidence',
    category: 'truth',
    dataType: 'number',
    operators: ['gt', 'gte', 'lt', 'lte', 'threshold'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'truth.dimension_state',
    label: 'Dimension state',
    category: 'truth',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
  {
    id: 'truth.evidence_basis',
    label: 'Evidence basis',
    category: 'truth',
    dataType: 'enum',
    operators: ['eq', 'neq', 'in', 'not_in'],
    sensitivity: 'tenant_internal',
  },
];
