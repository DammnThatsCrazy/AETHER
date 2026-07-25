from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_founding_tenant_surface",
    ROOT / "scripts/release/check_founding_tenant_surface.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_founding_tenant_manifest_matches_code_registries() -> None:
    assert MODULE.validate() == []


def test_rollout_stages_are_monotonic_and_bounded() -> None:
    assert MODULE.STAGES[0] == "disabled"
    assert MODULE.STAGES[-1] == "general_availability_candidate"
    assert len(MODULE.STAGES) == len(set(MODULE.STAGES))


def test_worker_readiness_alert_threshold_matches_the_probe_it_alerts_on() -> None:
    """The staleness alert and the readiness probe must agree on "stale".

    ``worker_readiness_stale_seconds`` is the window an operator gets paged on;
    ``HEARTBEAT_TIMEOUT_S`` is the window ``role_state()`` actually compares
    ``heartbeat_age_s`` against when deciding whether a release-critical role
    fails ``/v1/ready``. If the two drift apart, one of them is describing
    behaviour the platform does not have — either paging on a condition the probe
    tolerates, or staying silent through one it rejects.

    A comment asserting the two match is not enforcement, which is why this is a
    test.
    """
    import sys

    import yaml

    backend = ROOT / "Backend Architecture/aether-backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from services.runtime.supervisor import HEARTBEAT_TIMEOUT_S

    manifest = yaml.safe_load(
        (ROOT / "config/founding_tenant_release.yaml").read_text(encoding="utf-8")
    )
    declared = manifest["release_thresholds"]["worker_readiness_stale_seconds"]

    assert float(declared) == float(HEARTBEAT_TIMEOUT_S), (
        f"founding_tenant_release.yaml pages on a {declared}s staleness window "
        f"while supervisor.role_state() fails readiness at {HEARTBEAT_TIMEOUT_S}s"
    )
