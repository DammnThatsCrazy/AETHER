from datetime import date

from scripts.test_inventory import affected, build_inventory, violations


def config():
    return {
        "defaults": {"owner": "quality", "domain": "platform", "contract_protected": False,
                     "risk": "medium", "runtime_budget_seconds": 30, "dependencies": [],
                     "flakiness": "stable", "last_meaningful_failure": None,
                     "execution_lane": "pr", "duplicate_of": None, "status": "active",
                     "disposition": "KEEP"},
        "rules": [{"paths": ["tests/**"], "domain": "backend", "dependencies": ["app/**"]}],
        "quarantines": [],
    }


def test_inventory_rules_produce_complete_per_test_metadata():
    records = build_inventory(config(), ["tests/test_example.py"])
    assert records[0]["domain"] == "backend"
    assert violations(config(), records) == []


def test_changed_source_selects_only_declared_consumers():
    records = build_inventory(config(), ["tests/test_example.py", "other/test_unrelated.py"])
    assert affected(records, ["app/service.py"]) == ["tests/test_example.py"]


def test_changed_test_selects_itself_without_declared_dependencies():
    cfg = config()
    cfg["rules"] = []
    records = build_inventory(cfg, ["other/test_example.py"])
    assert affected(records, ["other/test_example.py"]) == ["other/test_example.py"]


def test_non_runnable_debt_is_not_selected():
    cfg = config()
    cfg["quarantines"] = [{
        "test_id": "tests/test_example.py", "owner": "quality",
        "reason": "flaky", "expires": "2099-01-01",
    }]
    records = build_inventory(cfg, ["tests/test_example.py"])
    assert affected(records, ["app/service.py", "tests/test_example.py"]) == []


def test_expired_quarantine_is_reported_as_debt():
    cfg = config()
    cfg["quarantines"] = [{"test_id": "tests/test_example.py", "owner": "quality", "reason": "flaky", "expires": "2026-01-01"}]
    records = build_inventory(cfg, ["tests/test_example.py"])
    assert violations(cfg, records, today=date(2026, 8, 31)) == [
        "quarantine tests/test_example.py: expired 2026-01-01"
    ]
