"""The seam gate must catch the defect shapes that actually shipped.

A validator that passes on a healthy tree proves nothing on its own — the
question is whether it fails on a broken one. Each case below is a real defect
that reached the merge queue in the first Kyber release, replayed against the
checker.

The nonexistent-module case is here for a specific reason: the first revision
of the validator treated an unimportable module as tolerable when the seam was
marked ``optional``, and therefore MISSED the highest-impact defect it was
written to catch. ``optional`` means the caller degrades gracefully at runtime;
it never means a declared module may be absent.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "seam-test")


def _validator():
    spec = importlib.util.spec_from_file_location(
        "_kyber_seam_validator", ROOT / "scripts" / "validate_kyber_seams.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(seam) -> list[str]:
    validator = _validator()
    validator.FAILURES.clear()
    validator.check(seam)
    return list(validator.FAILURES)


def test_declared_seams_all_resolve():
    """The live declarations must hold — this is the gate's day job."""
    assert _validator().main() == 0


def test_nonexistent_module_is_caught_even_when_optional():
    """The defect the first validator revision missed.

    `lifecycle` imported `services.kyber.devices.service`, which has never
    existed (it is `devices.approvals`). Offboarding reported success while
    leaving every device approved.
    """
    from services.kyber.seams import Seam

    failures = _check(
        Seam(
            caller="test",
            module="services.kyber.devices.service",
            singleton="device_service",
            attribute="revoke_device",
            optional=True,
        )
    )
    assert failures, "an optional seam must not excuse a module that does not exist"
    assert "does not import" in failures[0]


def test_wrong_singleton_name_is_caught():
    """`scope_service` vs the real `access_scope_service`."""
    from services.kyber.seams import Seam

    failures = _check(
        Seam(
            caller="test",
            module="services.kyber.access.scopes",
            singleton="scope_service",
            attribute="revoke_for_operator",
        )
    )
    assert failures
    # The message must name what IS exported, or it sends the reader hunting.
    assert "access_scope_service" in failures[0]


def test_unaccepted_keyword_is_caught():
    """The access dependency passed kwargs `check_kyber_access` does not accept,
    so Kyber decisions never reached `security_policy_decisions`."""
    from services.kyber.seams import Seam

    failures = _check(
        Seam(
            caller="test",
            module="services.security.policy_engine",
            singleton="policy_engine",
            attribute="check_kyber_access",
            keywords=("blast_radius", "rollback_plan"),
        )
    )
    assert failures
    assert "does not accept keyword" in failures[0]


def test_wrong_method_name_is_caught():
    """Logout called `revoke_session()`; the method is `revoke()`."""
    from services.kyber.seams import Seam

    failures = _check(
        Seam(
            caller="test",
            module="services.kyber.sessions.service",
            singleton="session_service",
            attribute="revoke_session",
        )
    )
    assert failures
    assert "does not exist" in failures[0]


def test_positional_arity_overrun_is_caught():
    from services.kyber.seams import Seam

    failures = _check(
        Seam(
            caller="test",
            module="services.kyber.access.scopes",
            singleton="access_scope_service",
            attribute="revoke_for_operator",
            positional=5,
        )
    )
    assert failures
    assert "positional" in failures[0]


def test_every_kyber_cross_package_import_is_declared():
    """A function-level import of another Kyber package must be declared.

    This is what stops the registry from silently falling behind the code: a
    new undeclared seam is exactly the situation that produced both shipped
    defects.
    """
    import re

    from services.kyber.seams import SEAMS

    declared = {s.module for s in SEAMS}
    kyber_root = BACKEND / "services" / "kyber"
    pattern = re.compile(r"^\s+from (services\.(?:kyber|security)\.[\w.]+) import", re.M)

    undeclared: dict[str, set[str]] = {}
    for path in kyber_root.rglob("*.py"):
        # `access.contracts`, `.capabilities`, `.roles`, `.disclosure` are leaf
        # modules imported at module scope by design — they hold no behaviour to
        # drift against. Seams are about CALLS into another plane's service.
        for module in pattern.findall(path.read_text()):
            if module.endswith((".contracts", ".capabilities", ".roles", ".disclosure")):
                continue
            if module not in declared:
                undeclared.setdefault(str(path.relative_to(BACKEND)), set()).add(module)

    assert not undeclared, (
        "function-level cross-package imports that are not declared in "
        "services/kyber/seams.py:\n"
        + "\n".join(f"  {f}: {sorted(m)}" for f, m in sorted(undeclared.items()))
        + "\nAdd a Seam entry so the gate can prove the target resolves."
    )
