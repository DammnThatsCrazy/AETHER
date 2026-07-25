"""The four command-lifecycle routes are gated by their spec, not by the floor.

`config/route_registry.yaml` declares `POST /v1/kyber/ops/commands`,
`/dry-run`, `/approve` and `/execute` at `kyber.workforce.self.read`, D0,
action class 0. Read alone, that looks like an unguarded route for a plane whose
most dangerous member engages a fleet-wide kill switch.

It is not, and the reason is worth stating precisely: a command's capability and
action class come from its own `CommandSpec`, which is not known until the
request body has been read. `activate_kill_switch` is class 5;
`retry_job` is class 2. One route dependency cannot declare both, and declaring
the ceiling would deny a routine retry to an operator who legitimately holds
only `kyber.command.retry` — a control that blocks the ordinary case is a
control operators learn to route around.

So the dependency declares a floor that grants nothing, and the handler calls
`resolve_access_context` with the spec's real capability, real action class, D4,
and `tenant_scope="required"` where the spec is tenant-scoped. **That call is
the gate.** These tests exist because that arrangement is only safe while the
nested call is actually there and actually passes the spec's own values — and
nothing else in the suite would notice if it stopped. A regression here would
leave the route registry looking correctly declared while a class-5 command
executed under a class-0 evaluation.

The tests are structural rather than end-to-end on purpose: exercising the real
dependency needs live session, principal and device providers, and a test that
needs a fixture that large is a test that gets deleted. Structure is what is at
risk here anyway — the gate disappearing, or being called with the wrong
argument — not the evaluator's own logic, which
`tests/security/test_kyber_gate_consolidation.py` already covers.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
ROUTES = BACKEND / "services" / "kyber" / "ops" / "routes.py"

#: The four handlers whose authorization is deferred to the command spec.
NESTED_HANDLERS: tuple[str, ...] = (
    "request_command",
    "dry_run_command",
    "approve_command",
    "execute_command",
)

#: The floor the route registry declares for them. Held by every authenticated
#: principal; it authorizes nothing on its own.
FLOOR_CAPABILITY = "kyber.workforce.self.read"


def _module_tree() -> ast.Module:
    return ast.parse(ROUTES.read_text())


def _function(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(
        f"{name!r} is not defined in services/kyber/ops/routes.py. If a command "
        f"lifecycle route was renamed, update NESTED_HANDLERS — do not delete "
        f"the assertion, because the nested gate is the only thing standing "
        f"between the declared floor and a class-5 command."
    )


def _calls(fn: ast.AsyncFunctionDef) -> list[ast.Call]:
    return [node for node in ast.walk(fn) if isinstance(node, ast.Call)]


@pytest.mark.parametrize("handler", NESTED_HANDLERS)
def test_every_command_lifecycle_handler_authorizes_against_its_spec(handler: str):
    """The handler must call `_authorize_command`, not rely on its dependency."""
    fn = _function(handler)
    names = {
        call.func.id
        for call in _calls(fn)
        if isinstance(call.func, ast.Name)
    }
    assert "_authorize_command" in names, (
        f"{handler} does not call _authorize_command. Its route dependency only "
        f"declares {FLOOR_CAPABILITY!r}, which grants nothing, so without the "
        f"nested call this endpoint has no capability gate at all."
    )


#: Command-service calls that only read. Three of the four handlers must call
#: one of these *before* authorizing, and the ordering is forced rather than
#: sloppy: the capability that gates the request is the command's own spec's,
#: and you cannot know the spec without first reading which command was named.
#:
#: The residue is a narrow existence signal — a principal holding only the inert
#: floor learns 404-vs-403 for an opaque command id. That is accepted, not
#: overlooked: every caller here already holds a live session, an approved
#: device and a Kyber principal, command ids are unguessable, and the
#: alternative is a second lookup path that exists only to answer "what type is
#: this", which is a worse thing to maintain than a documented signal.
READ_ONLY_SERVICE_CALLS: frozenset[str] = frozenset({"require", "get"})

#: Every command-service call that changes state. None may precede the gate.
MUTATING_SERVICE_CALLS: frozenset[str] = frozenset(
    {"request", "dry_run", "approve", "execute", "verify", "cancel"}
)


@pytest.mark.parametrize("handler", NESTED_HANDLERS)
def test_no_command_state_changes_before_the_nested_gate(handler: str):
    """Authorization must precede every mutation, not follow it.

    A gate that runs after the state change is not a gate; it is a log entry.
    Reads are permitted before it — see `READ_ONLY_SERVICE_CALLS` for why that
    ordering is forced — but nothing that writes.
    """
    fn = _function(handler)
    auth_line = None
    mutations: list[tuple[str, int]] = []
    for call in _calls(fn):
        if isinstance(call.func, ast.Name) and call.func.id == "_authorize_command":
            auth_line = call.lineno if auth_line is None else min(auth_line, call.lineno)
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "command_service"
        ):
            method = call.func.attr
            assert method in READ_ONLY_SERVICE_CALLS | MUTATING_SERVICE_CALLS, (
                f"{handler} calls command_service.{method}, which is classified "
                f"neither read-only nor mutating. Classify it — an unclassified "
                f"call is how a write slips in front of the gate."
            )
            if method in MUTATING_SERVICE_CALLS:
                mutations.append((method, call.lineno))

    assert auth_line is not None, f"{handler} never authorizes"
    for method, line in mutations:
        assert auth_line < line, (
            f"{handler} calls the mutating command_service.{method} at line "
            f"{line}, before authorizing at line {auth_line}"
        )


def test_authorize_command_passes_the_specs_own_capability_and_action_class():
    """The nested call must forward the spec's values, not constants.

    Hard-coding either one is the failure this whole arrangement exists to
    avoid: a fixed action class would evaluate `activate_kill_switch` under
    whatever `retry_job` needs.
    """
    fn = _function("_authorize_command")
    resolve = [
        call
        for call in _calls(fn)
        if isinstance(call.func, ast.Name) and call.func.id == "resolve_access_context"
    ]
    assert len(resolve) == 1, (
        "_authorize_command must make exactly one authorization call; found "
        f"{len(resolve)}"
    )
    call = resolve[0]

    positional = [ast.unparse(a) for a in call.args]
    assert any("spec.capability_id" in a for a in positional), (
        f"the spec's capability is not passed positionally: {positional}"
    )

    keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    assert "spec.action_class" in keywords.get("action_class", ""), (
        f"action_class must come from the spec, got {keywords.get('action_class')!r}"
    )
    assert "spec.tenant_scoped" in keywords.get("tenant_scope", ""), (
        f"tenant_scope must follow the spec, got {keywords.get('tenant_scope')!r}"
    )
    assert "D4" in keywords.get("disclosure", ""), (
        "a command carries record-level evidence and must evaluate at D4 or "
        f"above so step-up engages, got {keywords.get('disclosure')!r}"
    )


def test_the_registry_floor_is_a_capability_that_grants_nothing():
    """The declared floor must be inert, or the deferral is a real widening.

    If the floor ever became a capability that authorizes something on its own,
    these routes would be granting it to every caller before the spec's gate
    ran.
    """
    import sys

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from services.kyber.access.capabilities import CAPABILITIES

    floor = CAPABILITIES[FLOOR_CAPABILITY]
    assert floor.action_class == 0, (
        f"{FLOOR_CAPABILITY} is action class {floor.action_class}; a non-zero "
        f"floor would let a command route authorize a state change before the "
        f"spec's own gate runs"
    )


def test_every_registered_command_spec_would_be_evaluated_at_its_own_class():
    """No spec can slip through the deferral with a class the floor covers.

    A spec declaring class 0 would be indistinguishable from an ungated route,
    so the registry's own refusal to register an unverifiable command is
    re-asserted here from the route's point of view.
    """
    import sys

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from services.kyber.access.capabilities import CAPABILITIES
    from services.kyber.ops.registry import COMMAND_REGISTRY

    assert COMMAND_REGISTRY, "no commands registered; the deferral has nothing to gate"
    for command_type, spec in COMMAND_REGISTRY.items():
        assert spec.action_class >= 2, (
            f"{command_type} declares action class {spec.action_class}; a command "
            f"below the retry class would be evaluated no more strictly than the "
            f"inert route floor"
        )
        capability = CAPABILITIES[spec.capability_id]
        assert capability.action_class == spec.action_class, (
            f"{command_type} declares class {spec.action_class} but its "
            f"capability {spec.capability_id} is class {capability.action_class}; "
            f"the nested gate evaluates the spec's value, so a disagreement here "
            f"is a privilege escalation with no attacker in it"
        )
