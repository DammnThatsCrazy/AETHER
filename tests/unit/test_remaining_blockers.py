from __future__ import annotations

import asyncio
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / 'Backend Architecture' / 'aether-backend'
AGENT_ROOT = ROOT / 'Agent Layer'


@contextmanager
def backend_path():
    original = list(sys.path)
    sys.path.insert(0, str(BACKEND_ROOT))
    for prefix in ('config', 'shared', 'services', 'repositories'):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f'{prefix}.'):
                sys.modules.pop(name, None)
    try:
        yield
    finally:
        sys.path[:] = original


@contextmanager
def agent_path():
    original = list(sys.path)
    sys.path.insert(0, str(AGENT_ROOT))
    for prefix in ('config', 'agent_controller', 'feedback', 'guardrails', 'models', 'queue'):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f'{prefix}.'):
                sys.modules.pop(name, None)
    try:
        yield
    finally:
        sys.path[:] = original


def test_agent_main_rejects_inmemory_backend_outside_local(monkeypatch):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('AETHER_AGENT_QUEUE_BACKEND', 'inmemory')
    with agent_path():
        module = importlib.import_module('main')
        with pytest.raises(RuntimeError, match='only allowed in local mode'):
            module._resolve_queue_backend()


def test_controller_wrapper_and_feedback_store_are_durable(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('AETHER_GUARDRAILS_DB_PATH', str(tmp_path / 'guardrails.sqlite3'))
    monkeypatch.setenv('AETHER_FEEDBACK_DB_PATH', str(tmp_path / 'feedback.sqlite3'))
    with agent_path():
        wrapper = importlib.import_module('controller')
        canonical = importlib.import_module('agent_controller.controller')
        assert wrapper.AgentController is canonical.AgentController

        settings_module = importlib.import_module('config.settings')
        models = importlib.import_module('models.core')
        controller = wrapper.AgentController(settings_module.AgentLayerSettings(), use_celery=False)
        task = models.AgentTask(worker_type=settings_module.WorkerType.ENTITY_RESOLVER, priority=settings_module.TaskPriority.MEDIUM, payload={})
        task.result = models.TaskResult(task_id=task.task_id, worker_type=task.worker_type, success=True, confidence=0.8)
        controller._history.append(task)
        controller.record_human_feedback(task.task_id, approved=True, notes='looks good')
        stats = controller.feedback_stats()
        assert stats['total_feedback'] == 1
        assert stats['per_worker'][settings_module.WorkerType.ENTITY_RESOLVER.value]['approved'] == 1


@pytest.mark.asyncio
async def test_rewards_route_uses_real_fraud_and_attribution_engines(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_AUTH_DB_PATH', str(tmp_path / 'auth.sqlite3'))
    monkeypatch.setenv('AETHER_EVENT_BUS_DB_PATH', str(tmp_path / 'events.sqlite3'))
    monkeypatch.setenv('AETHER_GRAPH_DB_PATH', str(tmp_path / 'graph.sqlite3'))
    monkeypatch.setenv('AETHER_REPOSITORY_DB_PATH', str(tmp_path / 'repos.sqlite3'))
    monkeypatch.setenv('ORACLE_SIGNER_KEY', '1' * 64)
    monkeypatch.setenv('REWARD_CONTRACT_ADDRESS', '0x' + '2' * 40)
    monkeypatch.setenv('ORACLE_INTERNAL_KEY', 'internal')
    with backend_path():
        module = importlib.import_module('services.rewards.routes')
        body = module.EvaluateRequest(
            event_type='conversion',
            user_address='0x' + '3' * 40,
            channel='social',
            session_id='sess-1',
            properties={
                'touchpoints': [
                    {'channel': 'social', 'source': 'twitter', 'campaign': 'launch', 'timestamp': '2026-03-01T00:00:00+00:00', 'event_type': 'click', 'properties': {}}
                ],
                'velocity_1m': 1,
                'bot_probability': 0.1,
            },
        )
        score = await module._evaluate_fraud_score(body)
        weight = await module._resolve_attribution_weight(body)
        assert isinstance(score, float)
        assert 0.0 <= score <= 100.0
        assert weight == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_resolution_repository_uses_durable_repositories(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_AUTH_DB_PATH', str(tmp_path / 'auth.sqlite3'))
    monkeypatch.setenv('AETHER_GRAPH_DB_PATH', str(tmp_path / 'graph.sqlite3'))
    monkeypatch.setenv('AETHER_REPOSITORY_DB_PATH', str(tmp_path / 'repos.sqlite3'))
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')
    with backend_path():
        repos = importlib.import_module('repositories.repos')
        resolution = importlib.import_module('services.resolution.repository')
        graph_module = importlib.import_module('shared.graph.graph')
        cache_module = importlib.import_module('shared.cache.cache')

        base = repos.BaseRepository('test_records')
        await base.insert('rec-1', {'tenant_id': 't1', 'value': 5})
        assert (await base.find_by_id('rec-1'))['value'] == 5

        graph = graph_module.GraphClient()
        await graph.connect()
        cache = cache_module.CacheClient()
        # avoid real redis dial during this test
        cache._backend = cache_module._SQLiteCacheBackend(tmp_path / 'cache.sqlite3')
        cache._connected = True
        repo = resolution.ResolutionRepository(graph, cache)
        loc_id = await repo.upsert_location_vertex({'country_code': 'US', 'region': 'CA', 'city': 'SF'})
        assert loc_id == 'US:CA:SF'


@pytest.mark.asyncio
async def test_provider_key_vault_and_usage_meter_are_durable(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_REPOSITORY_DB_PATH', str(tmp_path / 'repos.sqlite3'))
    with backend_path():
        key_vault_module = importlib.import_module('shared.providers.key_vault')
        meter_module = importlib.import_module('shared.providers.meter')

        vault = key_vault_module.BYOKKeyVault('secret-key')
        await vault.store_key('tenant-1', 'alchemy', 'blockchain_rpc', 'live-key', endpoint='https://rpc.example')
        assert await vault.get_key('tenant-1', 'alchemy') == 'live-key'
        listed = await vault.list_keys('tenant-1')
        assert listed[0]['provider_name'] == 'alchemy'
        assert 'masked_key' in listed[0]

        meter = meter_module.UsageMeter()
        await meter.record('tenant-1', 'blockchain_rpc', 'alchemy', 'eth_call', 12.5, True)
        usage = await meter.get_usage('tenant-1')
        assert usage[0]['total_requests'] == 1
        assert usage[0]['method_breakdown']['eth_call'] == 1


@pytest.mark.asyncio
async def test_x402_and_onchain_records_persist_durably(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_EVENT_BUS_DB_PATH', str(tmp_path / 'events.sqlite3'))
    monkeypatch.setenv('AETHER_GRAPH_DB_PATH', str(tmp_path / 'graph.sqlite3'))
    monkeypatch.setenv('AETHER_REPOSITORY_DB_PATH', str(tmp_path / 'repos.sqlite3'))
    with backend_path():
        graph_module = importlib.import_module('shared.graph.graph')
        onchain_module = importlib.import_module('services.onchain.action_recorder')
        onchain_models = importlib.import_module('services.onchain.models')
        x402_graph_module = importlib.import_module('services.x402.economic_graph')
        x402_models = importlib.import_module('services.x402.models')

        graph = graph_module.GraphClient()
        await graph.connect()

        recorder = onchain_module.ActionRecorder(graph_client=graph)
        action = onchain_models.ActionRecord(agent_id='agent-1', action_type=onchain_models.ActionType.CALL, chain_id='1', vm_type='evm', contract_address='0xabc')
        await recorder.record(action)
        actions = await recorder.get_agent_actions('agent-1')
        assert len(actions) == 1

        econ = x402_graph_module.X402EconomicGraph(graph_client=graph)
        tx = x402_models.CapturedX402Transaction(
            capture_id='cap-1',
            payer_agent_id='agent-1',
            payee_service_id='svc-1',
            terms=x402_models.PaymentTerms(amount=2.0, token='USDC', chain='eip155:1', recipient='svc-1'),
            proof=None,
            response=None,
            request_url='https://svc.example/pay',
            request_method='POST',
            amount_usd=2.0,
            fee_eliminated_usd=0.058,
        )
        await econ.add_payment(tx, tenant_id='tenant-1')
        snapshot = await econ.get_graph_snapshot(tenant_id='tenant-1')
        assert snapshot['pending_payments'] == 1
