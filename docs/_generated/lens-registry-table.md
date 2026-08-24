<!-- DO NOT EDIT — generated from packages/shared/contracts/lens-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Projection Engine — Lens Registry

Contract version: `1.0.0`

Composable viewing frames a projection applies over canonical Aether truth — one default base lens (`standard`) plus domain/capability overlay lenses.

| Lens | Kind | Base | Domain | Subjects | Temporal modes | Default |
|---|---|---|---|---|---|---|
| `agent` | overlay | standard | agentic | `agent`, `entity` | `as_of`, `relative`, `window` |  |
| `attribution` | overlay | standard | attribution | `campaign`, `episode` | `compare`, `relative`, `window` |  |
| `campaign` | overlay | standard | campaign | `campaign`, `episode`, `population`, `source` | `compare`, `relative`, `window` |  |
| `communication` | overlay | standard | communication | `campaign`, `episode`, `source` | `as_of`, `relative`, `window` |  |
| `consent` | overlay | standard | consent | `entity`, `population` | `as_of`, `compare`, `window` |  |
| `data_quality` | overlay | standard | data_quality | `campaign`, `cluster`, `connection`, `entity`, `population`, `source` | `as_of`, `relative`, `window` |  |
| `deployment` | overlay | standard | deployment | `deployment`, `entity`, `infrastructure` | `as_of`, `relative`, `window` |  |
| `economic` | overlay | standard | economic | `campaign`, `entity`, `episode`, `population`, `source` | `compare`, `relative`, `window` |  |
| `episode` | overlay | standard | episode | `campaign`, `entity`, `episode` | `relative`, `window` |  |
| `evidence` | overlay | standard | evidence | `campaign`, `cluster`, `connection`, `entity`, `episode`, `relationship`, `source` | `as_of`, `compare`, `window` |  |
| `execution` | overlay | standard | execution | `agent`, `entity`, `episode` | `as_of`, `relative`, `window` |  |
| `fraud` | overlay | standard | fraud | `agent`, `entity`, `relationship` | `as_of`, `relative`, `window` |  |
| `geographic` | overlay | standard | spatial | `entity`, `population`, `source` | `compare`, `relative`, `window` |  |
| `infrastructure` | overlay | standard | infrastructure | `deployment`, `entity`, `infrastructure` | `as_of`, `relative`, `window` |  |
| `journey` | overlay | standard | journey | `campaign`, `entity`, `episode` | `compare`, `relative`, `window` |  |
| `operational` | overlay | standard | operational | `cluster`, `connection`, `source` | `as_of`, `relative`, `window` |  |
| `outcome` | overlay | standard | outcome | `campaign`, `entity`, `episode`, `population` | `compare`, `relative`, `window` |  |
| `payment` | overlay | standard | payment | `entity`, `source` | `compare`, `relative`, `window` |  |
| `policy` | overlay | standard | policy | `campaign`, `entity`, `population`, `source` | `as_of`, `relative`, `window` |  |
| `population` | overlay | standard | population | `cluster`, `entity`, `population` | `relative`, `window` |  |
| `relationship` | overlay | standard | relationship | `entity`, `relationship` | `as_of`, `relative`, `window` |  |
| `risk` | overlay | standard | risk | `cluster`, `entity`, `population`, `relationship` | `as_of`, `relative`, `window` |  |
| `security` | overlay | standard | security | `deployment`, `entity`, `infrastructure` | `as_of`, `relative`, `window` |  |
| `source` | overlay | standard | source | `connection`, `source` | `relative`, `window` |  |
| `standard` | base | — | general | `agent`, `campaign`, `cluster`, `connection`, `entity`, `episode`, `population`, `relationship`, `source` | `as_of`, `compare`, `relative`, `window` | yes |
| `temporal` | overlay | standard | temporal | `campaign`, `entity`, `episode`, `relationship`, `source` | `as_of`, `compare`, `relative`, `window` |  |
| `trust` | overlay | standard | trust | `entity`, `relationship`, `source` | `as_of`, `relative`, `window` |  |
| `wallet` | overlay | standard | wallet | `entity`, `source` | `as_of`, `relative`, `window` |  |
