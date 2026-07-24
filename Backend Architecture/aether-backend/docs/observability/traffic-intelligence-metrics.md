# Traffic Intelligence Metrics (spec §16)

Authoritative list of the observability signals emitted across the
traffic-intelligence path. All names are defined in
`services/traffic/metrics.py` (`METRIC_NAMES`) and emitted through the shared
collector (`shared.logger.logger.metrics`) and `shared.observability.emit_latency`.

Label cardinality is intentionally bounded to canonical registry vocabulary
(source_class, proof_level, correlation status, entry-method state). Metric
names and their labels are stable — dashboards and the Kyber operator route
depend on them.

| Metric | Type | Labels | Emitted from |
|---|---|---|---|
| `classification_total` | counter | `source_class`, `proof_level` (one increment per dimension) | `services/silver/dispatcher.py` (per resolved touchpoint) |
| `direct_unknown_total` | counter | — | dispatcher (source_class == direct_unknown) |
| `evidence_conflict_total` | counter | — | dispatcher (per conflicting-evidence signal) |
| `machine_excluded_total` | counter | — | dispatcher (machine actor, attribution-ineligible) |
| `invalid_source_link_total` | counter | — | `services/traffic/routes.py` redirect (unresolvable token) |
| `source_link_replay_total` | counter | — | dispatcher (consumed handoff replay) |
| `handoff_correlation_total` | counter | `status` ∈ {success, expired, failed} | dispatcher (verified-referral handoff resolution) |
| `redirect_latency_ms` | latency | — | redirect endpoint (`emit_latency("redirect", …)`) |
| `navigation_correlation_total` | counter | `status` | web navigation correlation hook |
| `install_referrer_retrieval_total` | counter | `state` ∈ {retrieved, empty, unavailable, error} | Android install-referrer hook |
| `app_link_processing_total` | counter | — | Android App Link processing hook |
| `universal_link_processing_total` | counter | — | iOS Universal Link processing hook |
| `deferred_attribution_total` | counter | `status` ∈ {resolved, unmatched, expired} | deferred-attribution resolution hook |
| `adattributionkit_ingestion_total` | counter | — | AdAttributionKit ingestion hook (`record_adattributionkit_ingestion`) |
| `sdk_deep_link_parse_failure_total` | counter | — | SDK deep-link parse hook |
| `reclassification_throughput_total` | counter | — | `services/traffic/repair.py` (rows reclassified) |
| `reclassification_failure_total` | counter | — | repair.py (per-run errors / hard failure) |
| `shadow_divergence_total` | counter | `diverged` ∈ {true, false} | `services/traffic/shadow.py` shadow-compare |

## Hooks exposed for other agents

`services/traffic/metrics.py` exposes named helpers so web/native agents emit
these signals consistently rather than calling `metrics.increment` with ad-hoc
names:

- `record_navigation_correlation(status)`
- `record_install_referrer_retrieval(state)`
- `record_app_link_processing()`
- `record_universal_link_processing()`
- `record_deferred_attribution(status)`
- `record_adattributionkit_ingestion()`
- `record_sdk_deep_link_parse_failure()`

## Dashboard contribution

`traffic_metrics_summary()` returns the current counter snapshot for just this
metric family and is folded into `shared.observability.metrics_summary()` under
the `counters.traffic_intelligence` key.
