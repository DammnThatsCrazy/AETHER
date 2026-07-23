"""Honesty gate: semantic alerts/dashboard reference only REAL metric series.

Pins the ``aether_semantic_health`` Prometheus alert group and the
``semantic-pipeline`` Grafana dashboard to the exact metric names emitted by
``services/semantic_intelligence`` — an alert or panel referencing a series
nothing emits would be silently dead forever. Also asserts both assets parse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

ALERT_RULES = ROOT / "deploy/observability/prometheus/alert_rules.yml"
DASHBOARD = ROOT / "deploy/observability/grafana/dashboards/semantic-pipeline.json"

# The complete metric contract emitted by
# Backend Architecture/aether-backend/services/semantic_intelligence.
# Any semantic alert expr or dashboard query MUST resolve to one of these.
CONTRACTED_METRICS = frozenset(
    {
        "aether_semantic_observations_classified_total",   # counter; labels: tenant_id
        "aether_semantic_observations_abstained_total",    # counter; labels: tenant_id, reason
        "aether_semantic_observations_quarantined_total",  # counter; labels: tenant_id, reason
        "aether_semantic_classify_latency_ms",             # histogram
        "aether_semantic_review_queue_open",               # gauge; labels: queue_type
        "aether_semantic_replay_jobs_active",              # gauge
    }
)

_METRIC_RE = re.compile(r"\baether_semantic_[a-z0-9_]+")
# Prometheus exposes a histogram as <name>_bucket/_sum/_count series.
_HISTOGRAM_SUFFIX_RE = re.compile(r"_(?:bucket|sum|count)$")

# Identifiers that match the aether_semantic_* pattern but are NOT metric
# series (the alert group's own name). Kept explicit so nothing hides here.
NON_METRIC_TOKENS = frozenset({"aether_semantic_health"})


def _extract_metric_names(text: str) -> set[str]:
    """All aether_semantic_* series in ``text``, histogram suffixes normalized."""
    names = {_HISTOGRAM_SUFFIX_RE.sub("", name) for name in _METRIC_RE.findall(text)}
    return names - NON_METRIC_TOKENS


def _semantic_alert_group() -> dict:
    doc = yaml.safe_load(ALERT_RULES.read_text(encoding="utf-8"))
    groups = [g for g in doc.get("groups", []) if g.get("name") == "aether_semantic_health"]
    assert groups, "aether_semantic_health group missing from alert_rules.yml"
    return groups[0]


def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def test_alert_rules_yaml_parses_and_group_has_rules():
    group = _semantic_alert_group()
    rules = group.get("rules", [])
    assert len(rules) >= 3
    for rule in rules:
        assert rule.get("alert"), f"unnamed rule in aether_semantic_health: {rule}"
        assert rule.get("expr"), f"rule {rule.get('alert')} has no expr"


def test_alert_group_references_only_contracted_metrics():
    group = _semantic_alert_group()
    for rule in group["rules"]:
        referenced = _extract_metric_names(str(rule["expr"]))
        assert referenced, f"alert {rule['alert']} references no semantic metric"
        unknown = referenced - CONTRACTED_METRICS
        assert not unknown, (
            f"alert {rule['alert']} references series services/semantic_intelligence "
            f"does not emit: {sorted(unknown)}"
        )


def test_dashboard_json_parses_and_panels_reference_only_contracted_metrics():
    dash = _dashboard()
    exprs: list[str] = []
    for panel in dash.get("panels", []):
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if expr:
                exprs.append(expr)
    assert exprs, "semantic-pipeline.json has no panel queries"
    for expr in exprs:
        referenced = _extract_metric_names(expr)
        assert referenced, f"panel expr references no semantic metric: {expr}"
        unknown = referenced - CONTRACTED_METRICS
        assert not unknown, (
            f"panel expr references series services/semantic_intelligence does not "
            f"emit: {sorted(unknown)} in {expr!r}"
        )


def test_no_uncontracted_semantic_series_anywhere_in_either_asset():
    """Whole-file sweep (templating queries, annotations, comments included)."""
    for path in (ALERT_RULES, DASHBOARD):
        referenced = _extract_metric_names(path.read_text(encoding="utf-8"))
        unknown = referenced - CONTRACTED_METRICS
        assert not unknown, f"{path.name} references uncontracted series: {sorted(unknown)}"


def test_dashboard_and_alerts_cover_every_contracted_metric_family():
    """Between them, the assets observe the full contract (no blind spots)."""
    referenced = _extract_metric_names(ALERT_RULES.read_text(encoding="utf-8"))
    referenced |= _extract_metric_names(DASHBOARD.read_text(encoding="utf-8"))
    missing = CONTRACTED_METRICS - referenced
    assert not missing, f"contracted series with no alert or panel: {sorted(missing)}"
