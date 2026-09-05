<!-- DO NOT EDIT — generated from packages/shared/contracts/surface-capability-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Surface Capability Registry

Contract version: `1.0.0`

## Temporal modes

`window`, `as_of`, `compare`, `relative`

## Views

`graph`, `table`, `map`, `timeline`, `flow`, `comparison`

## Filter dispositions

`applied`, `translated`, `unsupported`, `suppressed`, `not_applicable`

## Surfaces

| Surface | Field categories | Temporal modes | Views | Facets | Comparison | Selection sets | Saved views | Export |
|---|---|---|---|---|---|---|---|---|
| `campaign360` | `entity`, `time`, `geography`, `campaign`, `economic`, `truth` | `window`, `compare`, `relative` | `table`, `flow`, `timeline` | yes | yes | yes | yes | yes |
| `cluster360` | `entity`, `time`, `graph`, `risk`, `truth` | `window`, `as_of` | `graph`, `table` | yes | yes | yes | no | yes |
| `comparison_workbench` | `entity`, `time`, `geography`, `device`, `graph`, `risk`, `campaign`, `economic`, `truth` | `window`, `as_of`, `compare`, `relative` | `comparison`, `table`, `graph`, `timeline` | yes | yes | yes | yes | yes |
| `connection360` | `entity`, `time`, `graph`, `truth` | `window`, `as_of`, `relative` | `table`, `flow` | no | no | no | yes | yes |
| `economic360` | `entity`, `time`, `device`, `campaign`, `economic`, `truth` | `window`, `compare`, `relative` | `table`, `graph` | yes | yes | yes | yes | yes |
| `geo` | `entity`, `time`, `geography`, `campaign`, `risk` | `window`, `compare`, `relative` | `map`, `table` | yes | yes | yes | yes | yes |
| `geographic360` | `entity`, `time`, `geography`, `truth` | `window`, `compare`, `relative` | `map`, `table` | yes | yes | yes | yes | yes |
| `graph` | `entity`, `time`, `geography`, `device`, `graph`, `risk`, `campaign`, `economic`, `truth` | `window`, `as_of`, `relative` | `graph`, `table` | yes | no | yes | yes | yes |
| `infrastructure360` | `entity`, `time`, `graph`, `risk`, `truth` | `window`, `as_of`, `compare`, `relative` | `table`, `graph`, `map` | yes | yes | yes | yes | yes |
| `journeys` | `entity`, `time`, `device`, `campaign`, `truth` | `window`, `relative` | `flow`, `table`, `timeline` | yes | yes | yes | yes | yes |
| `outcome360` | `entity`, `time`, `geography`, `campaign`, `economic`, `truth` | `window`, `compare`, `relative` | `table`, `graph` | yes | yes | yes | yes | yes |
| `population360` | `entity`, `graph`, `time`, `truth` | `window`, `relative` | `table`, `timeline`, `comparison` | yes | yes | yes | yes | yes |
| `product_intelligence` | `entity`, `time`, `device`, `campaign`, `economic`, `truth` | `window`, `compare`, `relative` | `table`, `timeline`, `flow` | yes | yes | yes | yes | yes |
| `profile360` | `entity`, `time`, `geography`, `device`, `campaign`, `economic`, `risk`, `truth` | `window`, `as_of`, `relative` | `table`, `timeline` | no | yes | no | no | yes |
| `social360` | `entity`, `time`, `social`, `relationship`, `incentive`, `source`, `evidence`, `path`, `narrative` | `window`, `as_of`, `relative` | `table`, `graph` | yes | no | yes | no | yes |
| `temporal360` | `entity`, `time`, `truth` | `window`, `as_of`, `compare`, `relative` | `timeline`, `table` | yes | yes | yes | yes | yes |
| `temporal_observatory` | `entity`, `time`, `truth` | `window`, `as_of`, `compare`, `relative` | `timeline`, `table` | no | yes | no | yes | yes |
| `timeline` | `entity`, `time`, `device`, `campaign`, `truth` | `window`, `as_of`, `relative` | `timeline`, `table` | no | no | yes | no | yes |
