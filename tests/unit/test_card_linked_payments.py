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
