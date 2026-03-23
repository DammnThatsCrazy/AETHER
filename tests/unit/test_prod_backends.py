from __future__ import annotations

import asyncio
import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / 'Backend Architecture' / 'aether-backend'
AGENT_ROOT = ROOT / 'Agent Layer'


@contextmanager
def backend_module_path():
    original = list(sys.path)
    sys.path.insert(0, str(BACKEND_ROOT))
    for prefix in ('config', 'shared', 'services'):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f'{prefix}.'):
                sys.modules.pop(name, None)
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ('config', 'shared', 'services'):
            for name in list(sys.modules):
                if name == prefix or name.startswith(f'{prefix}.'):
                    sys.modules.pop(name, None)


@contextmanager
def agent_module_path():
    original = list(sys.path)
    sys.path.insert(0, str(AGENT_ROOT))
    for prefix in ('config', 'guardrails', 'models'):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f'{prefix}.'):
                sys.modules.pop(name, None)
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ('config', 'guardrails', 'models'):
            for name in list(sys.modules):
                if name == prefix or name.startswith(f'{prefix}.'):
                    sys.modules.pop(name, None)


def test_api_key_validator_uses_durable_store(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_AUTH_DB_PATH', str(tmp_path / 'auth.sqlite3'))
    with backend_module_path():
        auth = importlib.import_module('shared.auth.auth')
        validator = auth.APIKeyValidator(environment='production')
        api_key = validator.provision_key(
            tenant_id='tenant_prod',
            role=auth.Role.EDITOR.value,
            tier=auth.APIKeyTier.PRO.value,
            permissions=['read', 'write'],
        )
        ctx = validator.validate(api_key)
        assert ctx.tenant_id == 'tenant_prod'
        assert ctx.permissions == ['read', 'write']
        validator._store.upsert_key(api_key, tenant_id='tenant_prod', revoked=True)
        with pytest.raises(auth.UnauthorizedError, match='revoked'):
            validator.validate(api_key)


@pytest.mark.asyncio
async def test_sqlite_event_bus_is_durable(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_EVENT_BUS_DB_PATH', str(tmp_path / 'events.sqlite3'))
    monkeypatch.setenv('AETHER_AUTH_DB_PATH', str(tmp_path / 'auth.sqlite3'))
    with backend_module_path():
        events = importlib.import_module('shared.events.events')
        producer = events.EventProducer()
        consumer = events.EventConsumer()
        await producer.connect()
        handled = []

        async def handler(event):
            handled.append(event.payload['value'])

        consumer.subscribe(events.Topic.SDK_EVENTS_VALIDATED, handler)
        event = events.Event(topic=events.Topic.SDK_EVENTS_VALIDATED, payload={'value': 7})
        await producer.publish(event)
        assert await consumer.pump_once(events.Topic.SDK_EVENTS_VALIDATED) is True
        assert handled == [7]
        assert producer.published_count == 1


@pytest.mark.asyncio
async def test_graph_and_cache_require_real_backends_or_local_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_GRAPH_DB_PATH', str(tmp_path / 'graph.sqlite3'))
    monkeypatch.setenv('AETHER_AUTH_DB_PATH', str(tmp_path / 'auth.sqlite3'))
    monkeypatch.delenv('REDIS_HOST', raising=False)
    monkeypatch.delenv('REDIS_URL', raising=False)
    with backend_module_path():
        graph_module = importlib.import_module('shared.graph.graph')
        graph = graph_module.GraphClient()
        await graph.connect()
        v1 = graph_module.Vertex(vertex_id='u1', vertex_type=graph_module.VertexType.USER.value)
        v2 = graph_module.Vertex(vertex_id='s1', vertex_type=graph_module.VertexType.SESSION.value)
        await graph.add_vertex(v1)
        await graph.add_vertex(v2)
        await graph.add_edge(graph_module.Edge(from_vertex_id='u1', to_vertex_id='s1', edge_type=graph_module.EdgeType.HAS_SESSION.value))
        neighbors = await graph.get_neighbors('u1')
        assert [n.vertex_id for n in neighbors] == ['s1']

        cache_module = importlib.import_module('shared.cache.cache')
        cache = cache_module.CacheClient()
        with pytest.raises(RuntimeError, match='REDIS_URL or REDIS_HOST'):
            await cache.connect()


def test_oracle_signer_uses_real_signature_verification(monkeypatch):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET', 'test-secret')
    monkeypatch.setenv('AETHER_AUTH_DB_PATH', '/tmp/test-auth.sqlite3')
    with backend_module_path():
        signer_module = importlib.import_module('services.oracle.signer')
        verifier_module = importlib.import_module('services.oracle.verifier')
        config = signer_module.ProofConfig(
            signer_private_key='1' * 64,
            contract_address='0x' + '2' * 40,
            chain_id=1,
            proof_expiry_seconds=3600,
        )
        signer = signer_module.OracleSigner(config)
        proof = asyncio.run(signer.generate_proof('0x' + '3' * 40, 'conversion', 123))
        assert asyncio.run(signer.verify_proof(proof)) is True
        assert verifier_module.verify_reward_proof(proof, signer.signer_address) is True
        proof.signature = '0x' + '0' * 128
        assert verifier_module.verify_reward_proof(proof, signer.signer_address) is False


def test_guardrails_audit_and_cost_are_durable(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.setenv('AETHER_GUARDRAILS_DB_PATH', str(tmp_path / 'guardrails.sqlite3'))
    with agent_module_path():
        module = importlib.import_module('guardrails.guardrails')
        settings_module = importlib.import_module('config.settings')
        models = importlib.import_module('models.core')
        audit = module.AuditLogger()
        record = models.AuditRecord(task_id='t1', worker_type=settings_module.WorkerType.ENTITY_RESOLVER, action='resolve', confidence=0.9)
        audit.log(record)
        fetched = audit.get_records('t1')
        assert len(fetched) == 1
        cost = module.CostMonitor(max_hourly=5.0, max_daily=10.0)
        cost.record_cost(3.0)
        cost.record_cost(2.5)
        assert cost.hourly_spend >= 5.5
        assert cost.is_over_budget() is True
