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
