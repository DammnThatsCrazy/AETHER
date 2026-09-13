"""
Aether Agent Layer — Full Demo
Demonstrates all 10 workers, auto-discovery registry, feedback loop,
PII detection, and queue dispatch.

Run:  python main.py
"""

import logging
import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from agent_controller.controller import AgentController
from config.settings import AgentLayerSettings, TaskPriority, WorkerType
from models.core import AgentTask
from workers.registry import discover_workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("aether.main")


def main():
    # ── 1. Initialize settings & controller ──────────────────────────
    settings = AgentLayerSettings()
    controller = AgentController(settings, use_celery=False)  # force in-memory for demo

    # ── 2. Auto-discover and register all workers ────────────────────
    workers = discover_workers(controller.guardrails)
    controller.register_workers(workers)

    print(f"\n{'='*60}")
    print(f"Registered {len(workers)} workers: {controller.registered_workers}")
    print(f"Queue backend: {'Celery' if controller.using_celery else 'in-memory'}")
    print(f"{'='*60}\n")

    # ── 3. Submit discovery tasks ────────────────────────────────────

    # Web Crawler
    controller.submit_task(AgentTask(
        worker_type=WorkerType.WEB_CRAWLER,
        priority=TaskPriority.HIGH,
        payload={
            "target_url": "https://example.com/about",
            "entity_id": "company_001",
            "extract_fields": ["metadata", "entity_mentions"],
        },
    ))

    # API Scanner
    controller.submit_task(AgentTask(
        worker_type=WorkerType.API_SCANNER,
        priority=TaskPriority.MEDIUM,
        payload={
            "target_domain": "api.example.com",
            "entity_id": "company_001",
            "deep_scan": True,
        },
    ))

    # Social Listener
    controller.submit_task(AgentTask(
        worker_type=WorkerType.SOCIAL_LISTENER,
        priority=TaskPriority.MEDIUM,
        payload={
            "entity_id": "company_001",
            "keywords": ["example", "#ExampleProject"],
            "platforms": ["twitter", "reddit"],
            "max_results": 50,
        },
    ))

    # Chain Monitor
    controller.submit_task(AgentTask(
        worker_type=WorkerType.CHAIN_MONITOR,
        priority=TaskPriority.HIGH,
        payload={
            "entity_id": "wallet_001",
            "addresses": ["0x1234567890abcdef1234567890abcdef12345678"],
            "chains": ["ethereum", "polygon"],
            "min_value_usd": 100.0,
        },
    ))

    # Competitor Tracker
    controller.submit_task(AgentTask(
        worker_type=WorkerType.COMPETITOR_TRACKER,
        priority=TaskPriority.LOW,
        payload={
            "entity_id": "competitor_001",
            "domain": "competitor.io",
            "track_jobs": True,
        },
    ))

    # ── 4. Submit enrichment tasks ───────────────────────────────────

    # Entity Resolver
    controller.submit_task(AgentTask(
        worker_type=WorkerType.ENTITY_RESOLVER,
        priority=TaskPriority.MEDIUM,
        payload={
            "candidate_entities": [
                {"name": "Acme Inc", "domain": "acme.io"},
                {"name": "ACME Corp", "domain": "acmecorp.com"},
            ],
            "match_strategy": "llm_hybrid",
        },
    ))

    # Profile Enricher
    controller.submit_task(AgentTask(
        worker_type=WorkerType.PROFILE_ENRICHER,
        priority=TaskPriority.MEDIUM,
        payload={
            "entity_id": "company_001",
            "entity_type": "company",
            "known_data": {"website": "https://example.com", "industry": "defi"},
        },
    ))

    # Temporal Filler
    controller.submit_task(AgentTask(
        worker_type=WorkerType.TEMPORAL_FILLER,
        priority=TaskPriority.LOW,
        payload={
            "entity_id": "company_001",
            "timeline_events": [
                {"date": "2024-01-15T00:00:00", "type": "funding_round"},
                {"date": "2024-06-20T00:00:00", "type": "product_launch"},
                {"date": "2025-03-01T00:00:00", "type": "partnership"},
            ],
            "gap_threshold": "60d",
            "fill_strategy": "hybrid",
            "metric_fields": ["employee_count", "revenue_est"],
        },
    ))

    # Semantic Tagger
    controller.submit_task(AgentTask(
        worker_type=WorkerType.SEMANTIC_TAGGER,
        priority=TaskPriority.LOW,
        payload={
            "entity_id": "company_001",
            "text_corpus": [
                "Example is a defi lending protocol built on Ethereum",
                "Series A funding of $15M led by Paradigm",
                "Launched v2 with cross-chain bridge support",
            ],
            "model": "rule_based",
            "top_k": 3,
        },
    ))

    # Quality Scorer
    controller.submit_task(AgentTask(
        worker_type=WorkerType.QUALITY_SCORER,
        priority=TaskPriority.BACKGROUND,
        payload={
            "entity_id": "company_001",
            "entity_data": {
                "website": "https://example.com",
                "industry": "defi",
                "employee_count": 45,
                "founded_year": 2022,
                "funding_total_usd": 15_000_000,
                "description": None,
                "tech_stack": None,
            },
            "field_metadata": {
                "website": {"source": "web_crawl", "updated_at": "2025-12-01T00:00:00+00:00"},
                "industry": {"source": "crunchbase", "updated_at": "2025-06-15T00:00:00+00:00"},
                "employee_count": {"source": "clearbit", "updated_at": "2025-01-10T00:00:00+00:00"},
                "founded_year": {"source": "crunchbase", "updated_at": "2024-03-01T00:00:00+00:00"},
                "funding_total_usd": {"source": "crunchbase", "updated_at": "2025-09-01T00:00:00+00:00"},
            },
            "required_fields": [
                "website", "industry", "employee_count", "founded_year",
                "funding_total_usd", "description", "tech_stack",
                "headquarters", "legal_name",
            ],
        },
    ))

    # ── 5. Process the queue ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Queue depth: {controller.queue_depth}")
    print(f"{'='*60}\n")

    results = controller.drain_queue()

    # ── 6. Print results ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Processed {len(results)} tasks")
    print(f"{'='*60}\n")

    for r in results:
        status = "\u2713" if r.success else "\u2717"
        print(
            f"  {status} [{r.worker_type.value:>20}] "
            f"conf={r.confidence:.2f} — {r.task_id[:8]}..."
        )
        if r.error:
            print(f"    Error: {r.error}")

    # ── 7. Demonstrate feedback loop ─────────────────────────────────
    print(f"\n{'='*60}")
    print("Feedback Learning Loop Demo")
    print(f"{'='*60}\n")

    # Simulate human review feedback
    review_tasks = [t for t in controller.history if t.result]
    for i, task in enumerate(review_tasks[:5]):
        approved = task.result.confidence >= 0.6  # simulate human decision
        controller.record_human_feedback(
            task_id=task.task_id,
            approved=approved,
            notes=f"Demo feedback #{i+1}",
        )

    stats = controller.feedback_stats()
    print(f"  Total feedback events: {stats['total_feedback']}")
    if stats.get("approval_rate") is not None:
        print(f"  Overall approval rate: {stats['approval_rate']:.1%}")
    for wt, ws in stats.get("per_worker", {}).items():
        print(
            f"  {wt}: yield={ws['yield_rate']:.0%} "
            f"accept_th={ws['tuned_auto_accept']:.2f} "
            f"discard_th={ws['tuned_discard']:.2f} "
            f"boost={ws['priority_boost']:+d}"
        )

    # ── 8. Demonstrate PII detection ─────────────────────────────────
    print(f"\n{'='*60}")
    print("PII Detection Demo")
    print(f"{'='*60}\n")

    pii = controller.guardrails.pii_detector
    test_text = (
        "Contact John at john.doe@acme.com or 555-123-4567. "
        "SSN: 123-45-6789. Wallet: 0x1234567890abcdef1234567890abcdef12345678"
    )
    findings = pii.scan(test_text)
    print(f"  Input:    {test_text}")
    print(f"  Findings: {len(findings)} PII items detected")
    for f in findings:
        print(f"    - {f['type']}: '{f['value']}' (conf={f['confidence']:.2f}, layer={f['layer']})")
    print(f"  Redacted: {pii.redact(test_text)}")

    # ── 9. Demonstrate kill switch ───────────────────────────────────
    print(f"\n{'='*60}")
    print("Kill Switch Demo")
    print(f"{'='*60}\n")

    controller.guardrails.kill_switch.engage()
    try:
        controller.submit_task(AgentTask(
            worker_type=WorkerType.WEB_CRAWLER,
            priority=TaskPriority.HIGH,
            payload={"target_url": "https://example.com"},
        ))
    except RuntimeError as e:
        print(f"  Blocked as expected: {e}")

    controller.guardrails.kill_switch.release()
    print("  Kill switch released.\n")

    # ── 10. Audit trail ──────────────────────────────────────────────
    audit = controller.guardrails.audit_logger.get_records()
    print(f"{'='*60}")
    print(f"Audit trail: {len(audit)} records")
    print(f"{'='*60}\n")
    for a in audit[:5]:
        print(
            f"  \u2192 {a.action:>15} | task={a.task_id[:8]}... "
            f"| conf={a.confidence:.2f}"
        )
    if len(audit) > 5:
        print(f"  ... and {len(audit) - 5} more\n")


if __name__ == "__main__":
    main()
