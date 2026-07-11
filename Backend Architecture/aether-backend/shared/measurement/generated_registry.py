# DO NOT EDIT — generated from packages/shared/contracts/event-registry.json
# Run: python scripts/generate_contracts.py
# Source: packages/shared/contracts/metric-registry.json
# Contract version: 1

GENERATED_METRIC_REGISTRY_VERSION = "1"

# Metric name -> field dict. Field names mirror shared/measurement/registry.py's
# MetricDefinition so the parity test can compare the two source by source.
GENERATED_METRICS: dict[str, dict] = {
    "conversion_rate": {
        "name": 'conversion_rate',
        "version": '1',
        "unit": 'ratio',
        "description": 'Share of journeys that reached a conversion.',
        "lower": 0.0,
        "upper": 1.0,
        "allows_probability": False,
        "min_sample": 30,
    },
    "attributed_conversions": {
        "name": 'attributed_conversions',
        "version": '1',
        "unit": 'count',
        "description": 'Conversions credited under the active attribution model.',
        "lower": 0.0,
        "upper": None,
        "allows_probability": False,
        "min_sample": 1,
    },
    "revenue": {
        "name": 'revenue',
        "version": '1',
        "unit": 'currency',
        "description": 'Attributed revenue over the measurement window.',
        "lower": 0.0,
        "upper": None,
        "allows_probability": False,
        "min_sample": 1,
    },
    "touchpoints": {
        "name": 'touchpoints',
        "version": '1',
        "unit": 'count',
        "description": 'Distinct marketing touchpoints observed in the window.',
        "lower": 0.0,
        "upper": None,
        "allows_probability": False,
        "min_sample": 1,
    },
    "journey_completion_rate": {
        "name": 'journey_completion_rate',
        "version": '1',
        "unit": 'ratio',
        "description": 'Share of started journeys that completed.',
        "lower": 0.0,
        "upper": 1.0,
        "allows_probability": False,
        "min_sample": 20,
    },
}
