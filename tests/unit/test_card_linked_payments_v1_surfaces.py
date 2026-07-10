import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'Backend Architecture/aether-backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.card_linked_payments.clusters import generate_card_linked_clusters
from services.card_linked_payments.diagnostics import card_linked_diagnostics
from services.card_linked_payments.gold import rollup_flows
from services.card_linked_payments.graph_projector import project_card_linked_graph
from services.card_linked_payments.normalizer import normalize_onchain_observation, normalize_provider_webhook
from services.card_linked_payments.repositories import get_card_linked_repositories


def _flow(flow_id, basis, amount, **extra):
    return {
        'id': flow_id, 'tenant_id': 'tenant_card', 'actor_kind': 'human',
        'canonical_entity_id': 'user_1', 'wallet_address_hash': 'wallet_hash_1',
        'card_program_id': 'redotpay', 'issuer_id': 'rain', 'payment_network': 'visa',
        'rail': 'card' if basis == 'spend' else 'onchain', 'basis': basis,
        'chain': 'base', 'asset': 'usdc', 'amount_usd': amount,
        'campaign_id': 'camp_base_usdc', 'journey_id': 'journey_1',
        'source': 'provider_webhook' if basis == 'spend' else 'onchain_observer',
        'confidence': 'strong', 'evidence_refs': [flow_id],
        'reconciliation_state': 'provider_only' if basis == 'spend' else 'onchain_only',
        'occurred_at': '2026-07-10T00:00:00Z', 'observed_at': '2026-07-10T00:00:00Z',
        'created_at': '2026-07-10T00:00:00Z', 'updated_at': '2026-07-10T00:00:00Z',
        **extra,
    }


def test_gold_rollup_never_conflates_topup_and_spend():
    rollup = rollup_flows([_flow('topup_1', 'topup', '100'), _flow('spend_1', 'spend', '25')])
    assert rollup['card_topup_volume'] == '100'
    assert rollup['card_spend_volume'] == '25'
    assert rollup['card_linked_volume'] == '125'
    assert 'Card top-up/funding volume is separated from card spend volume.' in rollup['warnings']


def test_graph_projection_has_card_program_issuer_and_basis_edges():
    graph = project_card_linked_graph('tenant_card', [_flow('spend_1', 'spend', '25')])
    node_types = {n['type'] for n in graph['nodes']}
    assert {'CardLinkedFlow', 'CardProgram', 'CardIssuer', 'PaymentNetwork', 'Campaign', 'Journey', 'Chain', 'Token'} <= node_types
    assert any(e['type'] == 'ISSUED_BY' and e['basis'] == 'spend' and e['identity_merge_evidence'] is False for e in graph['edges'])


def test_provider_and_onchain_normalizers_enforce_basis_and_block_pii():
    provider = normalize_provider_webhook({'id': 'p1', 'tenant_id': 'tenant_card', 'basis': 'spend', 'amount_usd': '5'})
    assert provider.basis.value == 'spend'
    onchain = normalize_onchain_observation({'id': 'o1', 'tenant_id': 'tenant_card', 'tx_hash': '0xabc'})
    assert onchain.basis.value == 'topup'
    try:
        normalize_provider_webhook({'id': 'bad', 'tenant_id': 'tenant_card', 'pan': '4111'})
    except ValueError as exc:
        assert 'Blocked' in str(exc)
    else:
        raise AssertionError('blocked PAN accepted')


def test_clusters_are_review_only_behavioral_outputs():
    clusters = generate_card_linked_clusters([_flow('topup_1', 'topup', '100'), _flow('spend_1', 'spend', '25')])
    names = {c['name'] for c in clusters}
    assert 'redotpay card users' in names
    assert 'usdc card top-up users' in names
    assert all(c['review_only'] is True for c in clusters)


async def test_diagnostics_shape_after_repository_upsert():
    repos = get_card_linked_repositories()
    await repos.flows.upsert(_flow('diag_topup', 'topup', '50'))
    diag = await card_linked_diagnostics('tenant_card')
    assert diag['card_program_count'] >= 23
    assert diag['issuer_count'] >= 6
    assert diag['basis_breakdown']['topup'] >= 1
    assert diag['paymentscan_status'] == 'catalog_and_benchmarks_only'
