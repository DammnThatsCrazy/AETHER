/**
 * DO NOT EDIT — generated from packages/shared/contracts/location-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const locationRegistryContractVersion = '1.0.0' as const;

/** Role a location fact plays for its subject (residence, egress, venue, ...). */
export const locationRoles = [
  'network_egress',
  'observed_presence',
  'likely_residence',
  'primary_residence',
  'declared_address',
  'shipping_address',
  'billing_address',
  'workplace',
  'commercial_destination',
  'organization_registered',
  'agent_execution_region',
  'venue_association',
  'trip_destination',
] as const;
export type LocationRole = typeof locationRoles[number];

/** Region-type hierarchy (not US-only), continent down to locality. */
export const regionTypes = [
  'continent',
  'country',
  'admin_region',
  'admin_subregion',
  'metro_area',
  'city',
  'district',
  'locality',
] as const;
export type RegionType = typeof regionTypes[number];

export { locationPrecisionClasses, type LocationPrecisionClass } from './context-capsule';

/** Coordinate reference systems a LocationFact may carry. */
export const coordinateSystems = ['wgs84'] as const;
export type CoordinateSystem = typeof coordinateSystems[number];

/** Spatial cell schemes (client-computed strings; never a DB spatial index). */
export const cellSchemes = ['h3'] as const;
export type CellScheme = typeof cellSchemes[number];
