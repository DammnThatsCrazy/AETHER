import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod

def test_catalog_seed_and_aliases():
    catalog = load('Backend Architecture/aether-backend/services/payment_catalog/catalog.py', 'catalog')
    assert [p.slug for p in catalog.PAYMENTSCAN_CARD_PROGRAMS] == ['redotpay','kast','etherfi','plasma_one','karta','tria','gnosis','cypher','kolo','ready','bfinance','metamask','holyheld','bitget_wallet','avici','safepal','solayer','avalanche_card','exa','tuyo','solflare','phantom_cash','hyperbeat']
    assert [i.slug for i in catalog.PAYMENTSCAN_ISSUERS] == ['rain','wirex','bridge','ur','kulipa','immersve']
    assert catalog.resolve_slug('Redot Pay') == 'redotpay'
    assert catalog.resolve_slug('MetaMask Card') == 'metamask'

def test_models_block_pii_and_benchmark_only():
    models = load('Backend Architecture/aether-backend/services/card_linked_payments/models.py', 'models')
    try:
        models.reject_blocked_fields({'pan': '4111'})
    except ValueError as exc:
        assert 'Blocked' in str(exc)
    else:
        raise AssertionError('PAN was accepted')
    flow = models.CardLinkedFlowObserved.benchmark(tenant_id='t1', catalog_entity_id='card_program:redotpay', observed_at='2026-07-10T00:00:00Z')
    assert flow.source == models.CardLinkedSource.PAYMENTSCAN
    assert flow.basis == models.CardActivityBasis.BENCHMARK_ONLY
    assert flow.reconciliation_state == 'benchmark_only'


def test_feature_flags_default_off(monkeypatch):
    for var in (
        "AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED",
        "AETHER_PAYMENTSCAN_CATALOG_ENABLED",
        "AETHER_PAYMENTSCAN_BENCHMARKS_ENABLED",
        "AETHER_CARD_LINKED_PROFILE360_ENABLED",
        "AETHER_CARD_LINKED_CAMPAIGN_ATTRIBUTION_ENABLED",
        "AETHER_CARD_LINKED_CLUSTERING_ENABLED",
        "KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED",
        "AETHER_CARD_LINKED_EU_RESTRICTED_MODE",
        "AETHER_CARD_LINKED_APAC_RESTRICTED_MODE",
        "AETHER_CARD_LINKED_PROVIDER_PII_BLOCK",
    ):
        monkeypatch.delenv(var, raising=False)
    backend = str(ROOT / "Backend Architecture" / "aether-backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from config.settings import CardLinkedPaymentRailsConfig

    config = CardLinkedPaymentRailsConfig()
    assert config.enabled is False
    assert config.paymentscan_catalog_enabled is False
    assert config.paymentscan_benchmarks_enabled is False
    assert config.profile360_enabled is False
    assert config.campaign_attribution_enabled is False
    assert config.clustering_enabled is False
    assert config.kyber_enabled is False
    # Safety defaults are ON
    assert config.eu_restricted_mode is True
    assert config.apac_restricted_mode is True
    assert config.provider_pii_block is True


def test_blocked_fields_parity_between_ts_and_python():
    """The TS classification map and Python blocked set must agree."""
    import re

    models = load('Backend Architecture/aether-backend/services/card_linked_payments/models.py', 'models_parity')
    ts = (ROOT / "packages" / "shared" / "card-linked-payments.ts").read_text()
    ts_blocked = set(re.findall(r"^\s+(\w+): 'blocked',", ts, re.M))
    assert ts_blocked == set(models.BLOCKED_CARD_LINKED_FIELDS), (
        f"TS/Python blocked-field drift: only-ts={ts_blocked - set(models.BLOCKED_CARD_LINKED_FIELDS)} "
        f"only-py={set(models.BLOCKED_CARD_LINKED_FIELDS) - ts_blocked}"
    )
