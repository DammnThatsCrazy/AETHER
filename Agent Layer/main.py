"""Aether Agent Layer — local runner with explicit queue backend selection."""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import AgentLayerSettings, WorkerType, TaskPriority
from models.core import AgentTask
from agent_controller.controller import AgentController
from workers.registry import discover_workers
from queue.celery_app import is_celery_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
logger = logging.getLogger("aether.main")


def _resolve_queue_backend() -> bool:
    mode = os.getenv("AETHER_AGENT_QUEUE_BACKEND", "auto").lower()
    env = os.getenv("AETHER_ENV", "local").lower()
    celery_ready = is_celery_available()
    if mode == "celery":
        if not celery_ready:
            raise RuntimeError("AETHER_AGENT_QUEUE_BACKEND=celery requires a configured Celery/Redis backend")
        return True
    if mode == "inmemory":
        if env != "local":
            raise RuntimeError("In-memory agent queue backend is only allowed in local mode")
        return False
    if mode != "auto":
        raise RuntimeError("AETHER_AGENT_QUEUE_BACKEND must be one of: auto, celery, inmemory")
    if env != "local" and not celery_ready:
        raise RuntimeError("Non-local agent execution requires an available Celery/Redis queue backend")
    return celery_ready


def main():
    settings = AgentLayerSettings()
    use_celery = _resolve_queue_backend()
    controller = AgentController(settings, use_celery=use_celery)
    workers = discover_workers(controller.guardrails)
    controller.register_workers(workers)

    print(f"\n{'='*60}")
    print(f"Registered {len(workers)} workers: {controller.registered_workers}")
    print(f"Queue backend: {'Celery' if controller.using_celery else 'in-memory'}")
    print(f"{'='*60}\n")

    controller.submit_task(AgentTask(worker_type=WorkerType.WEB_CRAWLER, priority=TaskPriority.HIGH, payload={"target_url": "https://example.com/about", "entity_id": "company_001", "extract_fields": ["metadata", "entity_mentions"]}))
    controller.submit_task(AgentTask(worker_type=WorkerType.API_SCANNER, priority=TaskPriority.MEDIUM, payload={"target_domain": "api.example.com", "entity_id": "company_001", "deep_scan": True}))
    controller.submit_task(AgentTask(worker_type=WorkerType.SOCIAL_LISTENER, priority=TaskPriority.MEDIUM, payload={"entity_id": "company_001", "keywords": ["example", "#ExampleProject"], "platforms": ["twitter", "reddit"], "max_results": 50}))
    controller.submit_task(AgentTask(worker_type=WorkerType.CHAIN_MONITOR, priority=TaskPriority.HIGH, payload={"entity_id": "wallet_001", "addresses": ["0x1234567890abcdef1234567890abcdef12345678"], "chains": ["ethereum", "polygon"], "min_value_usd": 100.0}))
    controller.submit_task(AgentTask(worker_type=WorkerType.COMPETITOR_TRACKER, priority=TaskPriority.LOW, payload={"entity_id": "competitor_001", "domain": "competitor.io", "track_jobs": True}))
    controller.submit_task(AgentTask(worker_type=WorkerType.ENTITY_RESOLVER, priority=TaskPriority.MEDIUM, payload={"candidate_entities": [{"name": "Acme Inc", "domain": "acme.io"}, {"name": "ACME Corp", "domain": "acmecorp.com"}], "match_strategy": "llm_hybrid"}))
    controller.submit_task(AgentTask(worker_type=WorkerType.PROFILE_ENRICHER, priority=TaskPriority.MEDIUM, payload={"entity_id": "company_001", "entity_type": "company", "known_data": {"website": "https://example.com", "industry": "defi"}}))
    controller.submit_task(AgentTask(worker_type=WorkerType.TEMPORAL_FILLER, priority=TaskPriority.LOW, payload={"entity_id": "company_001", "timeline_events": [{"date": "2024-01-15T00:00:00", "type": "funding_round"}, {"date": "2024-06-20T00:00:00", "type": "product_launch"}, {"date": "2025-03-01T00:00:00", "type": "partnership"}], "gap_threshold": "60d", "fill_strategy": "hybrid", "metric_fields": ["employee_count", "revenue_est"]}))
    controller.submit_task(AgentTask(worker_type=WorkerType.SEMANTIC_TAGGER, priority=TaskPriority.LOW, payload={"entity_id": "company_001", "text_corpus": ["Example is a defi lending protocol built on Ethereum", "Series A funding of $15M led by Paradigm", "Launched v2 with cross-chain bridge support"], "model": "rule_based", "top_k": 3}))
    controller.submit_task(AgentTask(worker_type=WorkerType.QUALITY_SCORER, priority=TaskPriority.BACKGROUND, payload={"entity_id": "company_001", "entity_data": {"website": "https://example.com", "industry": "defi", "employee_count": 45, "founded_year": 2022, "funding_total_usd": 15_000_000, "description": None, "tech_stack": None}, "field_metadata": {"website": {"source": "web_crawl", "updated_at": "2025-12-01T00:00:00+00:00"}, "industry": {"source": "crunchbase", "updated_at": "2025-06-15T00:00:00+00:00"}, "employee_count": {"source": "clearbit", "updated_at": "2025-01-10T00:00:00+00:00"}, "founded_year": {"source": "crunchbase", "updated_at": "2024-03-01T00:00:00+00:00"}, "funding_total_usd": {"source": "crunchbase", "updated_at": "2025-09-01T00:00:00+00:00"}}, "required_fields": ["website", "industry", "employee_count", "founded_year", "funding_total_usd", "description", "tech_stack", "headquarters", "legal_name"]}))

    print(f"\n{'='*60}")
    print(f"Queue depth: {controller.queue_depth}")
    print(f"{'='*60}\n")
    results = controller.drain_queue()
    print(f"\n{'='*60}")
    print(f"Processed {len(results)} tasks")
    print(f"{'='*60}\n")
    for r in results:
        status = "✓" if r.success else "✗"
        print(f"  {status} [{r.worker_type.value:>20}] conf={r.confidence:.2f} — {r.task_id[:8]}...")
        if r.error:
            print(f"    Error: {r.error}")

    print(f"\n{'='*60}")
    print("Feedback Learning Loop Demo")
    print(f"{'='*60}\n")
    review_tasks = [t for t in controller.history if t.result]
    for task in review_tasks[:5]:
        approved = task.result.confidence >= 0.6
        controller.record_human_feedback(task.task_id, approved, notes="automated local-run review")
    stats = controller.feedback_stats()
    print(f"  Total feedback events: {stats['total_feedback']}")


if __name__ == '__main__':
    main()
