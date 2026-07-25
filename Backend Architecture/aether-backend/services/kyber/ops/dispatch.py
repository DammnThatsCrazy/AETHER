"""Resolving a command's declared handler, and calling it.

A :class:`~services.kyber.ops.contracts.CommandSpec` names its handler as a
dotted ``module.Class.method`` string. This module turns that string into a real
bound callable, adapts the :class:`~services.kyber.ops.contracts.CommandRequest`
into the arguments that callable actually takes, and returns a structured record
of what happened so :mod:`services.kyber.ops.verification` has something to
inspect.

Three commitments, each of which is a refusal rather than a preference.

**Resolution fails loudly.** There is no ``try/except ImportError`` that
degrades to a no-op here. ``services/kyber/seams.py`` documents two production
defects with exactly that shape — a wrong module path is indistinguishable from
an absent one, so a broken integration reports success. A command whose handler
cannot be resolved raises :class:`CommandDispatchError` at the moment it is
needed, and the command fails visibly rather than reporting a state change that
never happened.

**Resolution happens once.** Each handler path is resolved on first use and
cached, so the import cost is paid once and — more importantly — a rename cannot
be masked by a later call that happened to hit a warm path.

**The handler's return value is never swallowed.** ``handler_result`` carries
whatever the platform call returned, unmodified where it is already a mapping.
Verification's whole job is to inspect that value and then go and re-read the
world; discarding it would leave "the call returned" as the only available
evidence, which is the failure mode this plane exists to prevent.

Nothing here reimplements platform work. Every handler is an existing call —
``JobsService.retry``, ``JobsService.enqueue``,
``AgentRuntimeRepository.set_kill_switch``, ``ContainmentService.activate``. The
value added is that the call is now typed, argument-checked before it runs, and
recorded.
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from shared.logger.logger import get_logger

from .contracts import CommandExecution, CommandRequest, CommandSpec, now_iso

logger = get_logger("aether.kyber.ops.dispatch")


class CommandDispatchError(RuntimeError):
    """A handler could not be resolved, bound or called.

    Deliberately a :class:`RuntimeError` rather than a ``BadRequestError``: an
    unresolvable handler is a defect in the registry or in the platform module
    it names, not something the caller did wrong. Turning it into a 4xx would
    invite an operator to keep retrying a command that can never run.
    """


# ── Instance providers ───────────────────────────────────────────────────────
#
# A handler string names a class and a method, but the method needs a receiver.
# Each class is mapped to the module-level accessor the platform already uses to
# hand out its instance, so the command plane shares the same object the rest of
# the backend does rather than constructing a second one with its own state.

_INSTANCE_PROVIDERS: dict[str, tuple[str, str]] = {
    "services.jobs.service.JobsService": ("services.jobs.service", "get_jobs_service"),
    "services.agent.runtime_repository.AgentRuntimeRepository": (
        "services.agent.runtime_repository",
        "get_agent_runtime_repository",
    ),
    "services.kyber.ops.containment.ContainmentService": (
        "services.kyber.ops.containment",
        "containment_service",
    ),
}

#: Instances installed by tests, keyed by ``module.Class``. Substituting a fake
#: here is the supported seam; patching module globals is not, because a patch
#: that misses leaves the real handler wired up and the test still passes.
_INSTANCE_OVERRIDES: dict[str, Any] = {}


def set_handler_instance(class_path: str, instance: Any) -> None:
    """Install a handler receiver. Tests use this instead of patching globals."""
    _INSTANCE_OVERRIDES[class_path] = instance


def reset_handler_instances() -> None:
    """Drop every installed override and the resolution cache."""
    _INSTANCE_OVERRIDES.clear()
    _RESOLVED.clear()


# ── Resolution ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedHandler:
    """One handler string, proven to point at something callable."""

    path: str
    module_path: str
    class_name: str
    method_name: str
    owner: Any
    callable_: Callable[..., Any]

    @property
    def class_path(self) -> str:
        return f"{self.module_path}.{self.class_name}"

    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.callable_)


#: ``handler string -> ResolvedHandler``. Populated on first use.
_RESOLVED: dict[str, ResolvedHandler] = {}


def _split_handler(path: str) -> tuple[str, str, str]:
    """Split ``a.b.C.method`` into module, class and method.

    The last two segments are always the class and the method; everything before
    them is the module. Guessing the split by probing importable prefixes would
    make a typo in the class name look like a shorter module path, which is the
    ambiguity this whole module exists to remove.
    """
    parts = (path or "").split(".")
    if len(parts) < 3:
        raise CommandDispatchError(
            f"handler {path!r} is not a dotted 'module.Class.method' path"
        )
    return ".".join(parts[:-2]), parts[-2], parts[-1]


def _resolve_owner(class_path: str, module_path: str, class_name: str, cls: Any) -> Any:
    """The receiver a handler method should be called on.

    Raises:
        CommandDispatchError: No provider is declared for the class, the
            declared provider does not exist, or it yields something that is not
            an instance of the class the handler named.
    """
    override = _INSTANCE_OVERRIDES.get(class_path)
    if override is not None:
        return override

    provider = _INSTANCE_PROVIDERS.get(class_path)
    if provider is None:
        raise CommandDispatchError(
            f"no instance provider declared for {class_path!r}. Add one to "
            f"_INSTANCE_PROVIDERS naming the accessor the platform already uses; "
            f"constructing a second instance here would give the command plane "
            f"its own copy of state the rest of the backend shares."
        )

    provider_module_path, symbol_name = provider
    provider_module = importlib.import_module(provider_module_path)
    symbol = getattr(provider_module, symbol_name, None)
    if symbol is None:
        raise CommandDispatchError(
            f"{provider_module_path}.{symbol_name} does not exist; "
            f"{class_path!r} has no reachable instance"
        )

    owner = symbol
    if not isinstance(symbol, cls) and callable(symbol):
        owner = symbol()
    if not isinstance(owner, cls):
        raise CommandDispatchError(
            f"{provider_module_path}.{symbol_name} yielded "
            f"{type(owner).__name__}, not {class_name}"
        )
    return owner


def resolve_handler(path: str) -> ResolvedHandler:
    """Resolve a handler string to a bound callable, once, or raise.

    Args:
        path: A dotted ``module.Class.method`` string from a
            :class:`~services.kyber.ops.contracts.CommandSpec`.

    Returns:
        The cached :class:`ResolvedHandler`.

    Raises:
        CommandDispatchError: The module, class, method or instance provider
            could not be resolved. Every failure here is loud: an unresolvable
            handler that reported success is how two production defects shipped
            (see ``services/kyber/seams.py``).
    """
    cached = _RESOLVED.get(path)
    if cached is not None:
        return cached

    module_path, class_name, method_name = _split_handler(path)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise CommandDispatchError(
            f"handler {path!r} names module {module_path!r}, which does not "
            f"import: {exc}"
        ) from exc

    cls = getattr(module, class_name, None)
    if cls is None:
        raise CommandDispatchError(
            f"handler {path!r} names class {class_name!r}, which does not exist "
            f"in {module_path!r}"
        )

    method = getattr(cls, method_name, None)
    if method is None or not callable(method):
        raise CommandDispatchError(
            f"handler {path!r} names method {method_name!r}, which is not "
            f"callable on {class_name}"
        )

    owner = _resolve_owner(f"{module_path}.{class_name}", module_path, class_name, cls)
    bound = getattr(owner, method_name, None)
    if not callable(bound):
        raise CommandDispatchError(
            f"handler {path!r} did not bind to a callable on the resolved "
            f"{class_name} instance"
        )

    resolved = ResolvedHandler(
        path=path,
        module_path=module_path,
        class_name=class_name,
        method_name=method_name,
        owner=owner,
        callable_=bound,
    )
    _RESOLVED[path] = resolved
    logger.debug(f"kyber: resolved command handler {path} -> {type(owner).__name__}")
    return resolved


# ── Containment targets ──────────────────────────────────────────────────────
#
# Both dispatch and verification need to agree on *which* switch a containment
# command is supposed to have flipped. Deriving it in two places is how they
# would come to disagree, so it is derived once, here.

#: Default control per containment scope. A command may override it with
#: ``metadata["containment_control"]`` when it pauses something narrower.
_CONTAINMENT_CONTROLS: dict[str, str] = {
    "connector": "ingestion",
    "tenant": "ingestion",
    "feature": "feature",
    "worker": "worker",
    "model": "model_serving",
    "region": "region",
    "environment": "deployments",
    # A kill switch stops the agent runtime; it is not safe mode, which is a
    # broader and separately-named set of controls in containment.py.
    "global": "agent_runtime",
}


def containment_target(
    command: CommandRequest, spec: CommandSpec
) -> Optional[tuple[str, Optional[str], str]]:
    """``(scope, target, control)`` for a command that flips a switch.

    Returns ``None`` when the spec declares no containment scope — that is a
    command which changes state some other way, and verification must read the
    absence as "not applicable", never as "no switch was needed".
    """
    scope = spec.containment_scope
    if scope is None:
        return None

    control = str(command.metadata.get("containment_control") or "").strip()
    if not control:
        control = _CONTAINMENT_CONTROLS.get(scope, spec.command_type)

    target: Optional[str]
    if scope == "global":
        target = None
    elif scope == "tenant":
        target = command.tenant_ids[0] if command.tenant_ids else None
    else:
        target = command.resource_ids[0] if command.resource_ids else None
    return scope, target, control


# ── Argument adaptation ──────────────────────────────────────────────────────
#
# Each command type maps onto an existing call. The job types below are the
# durable job names the enqueue-backed commands submit; they are declared here
# rather than in the registry because they are an implementation detail of *how*
# the work reaches the jobs platform, not part of the command's contract.

_JOB_TYPES: dict[str, str] = {
    "requeue_import": "import.commit",
    "replay_event_range": "events.replay",
    "recompute_measurement": "measurement.recompute",
    "rebuild_graph_projection": "graph.projection.rebuild",
    "rollback_model": "model.rollback",
    "rollback_release": "release.rollback",
}

#: Sentinel tenant for a fleet-wide kill switch. ``set_kill_switch`` keys its
#: control record by tenant; a global switch has no tenant, and inventing a real
#: one would engage the switch for a customer who was never named.
FLEET_TENANT = "*"


@dataclass
class HandlerCall:
    """The exact call a command resolves to, before it is made."""

    handler: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    #: Extra work the adapter will perform after the primary call, named so a
    #: dry run can show it rather than surprise the operator at execution.
    follow_up: tuple[str, ...] = ()


def _tenant(command: CommandRequest) -> str:
    return command.tenant_ids[0] if command.tenant_ids else ""


def _resource(command: CommandRequest, key: str) -> Optional[str]:
    """A named resource from metadata, falling back to the first resource id."""
    value = command.metadata.get(key)
    if value:
        return str(value)
    return command.resource_ids[0] if command.resource_ids else None


def _job_payload(command: CommandRequest) -> dict[str, Any]:
    """The durable job payload for an enqueue-backed command.

    The operator-supplied ``payload`` is carried through untouched, and the
    command's own identifiers are added beside it so the resulting job can be
    traced back to the command that asked for it. Verification relies on
    ``correlation_id`` for exactly that.
    """
    supplied = command.metadata.get("payload")
    payload: dict[str, Any] = dict(supplied) if isinstance(supplied, dict) else {}
    payload.setdefault("kyber_command_id", command.command_id)
    payload.setdefault("kyber_command_type", command.command_type)
    payload.setdefault("requested_by", command.requested_by)
    payload.setdefault("reason", command.reason)
    if command.resource_ids:
        payload.setdefault("resource_ids", list(command.resource_ids))
    for key in ("window_start", "window_end", "from_offset", "to_offset"):
        if command.metadata.get(key) is not None:
            payload.setdefault(key, command.metadata[key])
    return payload


def build_call(command: CommandRequest, spec: CommandSpec) -> HandlerCall:
    """Adapt a command into the arguments its handler actually takes.

    Raises:
        CommandDispatchError: The command type has no adapter, or the adapter
            has nothing to name — a retry with no job id, say. Both are refused
            here rather than passed down as ``None``, because a handler called
            with a missing identifier fails somewhere less legible.
    """
    command_type = command.command_type

    if command_type == "retry_job":
        job_id = _resource(command, "job_id")
        if not job_id:
            raise CommandDispatchError(
                "retry_job requires a job id in resource_ids or metadata['job_id']"
            )
        return HandlerCall(handler=spec.handler, args=(_tenant(command), job_id))

    if command_type in _JOB_TYPES:
        return HandlerCall(
            handler=spec.handler,
            args=(_tenant(command), _JOB_TYPES[command_type], _job_payload(command)),
            kwargs={
                # The command's own idempotency key becomes the job's, so a
                # replayed command cannot become a second unit of durable work.
                "idempotency_key": f"kyber:{command.command_type}:{command.idempotency_key}",
                "correlation_id": command.command_id,
                "requested_by": command.requested_by,
            },
        )

    if command_type in ("pause_connector", "pause_tenant_ingestion"):
        resolved = containment_target(command, spec)
        if resolved is None:
            raise CommandDispatchError(
                f"{command_type} declares no containment_scope; it cannot pause "
                f"anything"
            )
        scope, target, control = resolved
        if scope != "global" and not target:
            raise CommandDispatchError(
                f"{command_type} needs a {scope} target in "
                f"{'tenant_ids' if scope == 'tenant' else 'resource_ids'}"
            )
        return HandlerCall(
            handler=spec.handler,
            kwargs={
                "scope": scope,
                "target": target,
                "control": control,
                "actor_id": command.requested_by,
                "reason": command.reason,
                "blast_radius": command.blast_radius,
            },
        )

    if command_type == "activate_kill_switch":
        return HandlerCall(
            handler=spec.handler,
            args=(
                _tenant(command) or FLEET_TENANT,
                True,
                command.requested_by,
                command.reason,
                command.command_id,
            ),
            follow_up=("record_containment_switch",),
        )

    raise CommandDispatchError(
        f"command type {command_type!r} is registered but has no dispatch "
        f"adapter; a registered command with no way to run is a gate with no "
        f"door behind it"
    )


def _bind(resolved: ResolvedHandler, call: HandlerCall) -> Optional[str]:
    """Check the arguments against the handler's real signature.

    Returns the bound-argument summary, or raises. Binding before calling is
    what makes a dry run worth running: a signature drift is caught without any
    side effect at all.
    """
    try:
        signature = inspect.signature(resolved.callable_)
    except (TypeError, ValueError):  # pragma: no cover - C callables
        return None
    try:
        bound = signature.bind(*call.args, **call.kwargs)
    except TypeError as exc:
        raise CommandDispatchError(
            f"handler {resolved.path} does not accept the arguments "
            f"{call.handler} was adapted to: {exc}"
        ) from exc
    return ", ".join(sorted(bound.arguments))


# ── Planning and execution ───────────────────────────────────────────────────


async def plan(command: CommandRequest, spec: CommandSpec) -> dict[str, Any]:
    """What a command *would* do, without doing any of it.

    Resolves the handler, adapts the arguments and binds them against the real
    signature. Nothing is called. A dry run that only echoed the request back
    would prove nothing; this one proves the handler exists and the call is
    well-formed, which are the two failures that would otherwise surface
    mid-execution.
    """
    resolved = resolve_handler(spec.handler)
    call = build_call(command, spec)
    bound = _bind(resolved, call)
    containment = containment_target(command, spec)
    return {
        "command_id": command.command_id,
        "command_type": command.command_type,
        "handler": resolved.path,
        "handler_is_async": resolved.is_async(),
        "receiver": type(resolved.owner).__name__,
        "positional_arguments": [_render(value) for value in call.args],
        "keyword_arguments": {key: _render(value) for key, value in call.kwargs.items()},
        "bound_parameters": bound,
        "follow_up": list(call.follow_up),
        "containment_target": (
            {"scope": containment[0], "target": containment[1], "control": containment[2]}
            if containment
            else None
        ),
        "verification_plan": list(spec.verification_checks),
        "planned_at": now_iso(),
    }


def _render(value: Any) -> Any:
    """A body-safe rendering of one argument for the dry-run plan."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _render(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_render(item) for item in value]
    return repr(value)


async def _call(resolved: ResolvedHandler, call: HandlerCall) -> Any:
    """Invoke the handler, awaiting it when it is a coroutine function.

    Sync and async handlers both occur in this codebase, and the awaitable check
    is on the *returned value* rather than only on the function, so a sync
    wrapper that returns a coroutine is still awaited.
    """
    result = resolved.callable_(*call.args, **call.kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _record_containment_switch(
    command: CommandRequest, spec: CommandSpec
) -> Optional[str]:
    """Write the containment switch a non-containment handler implies.

    Only runs for a command that declares ``containment_switch_active`` among
    its verification checks while dispatching to something other than the
    containment service — today, ``activate_kill_switch``, whose registry
    description says exactly this. Deriving the follow-up from the declaration
    rather than from a hardcoded list means a future command that declares the
    same check gets the same behaviour instead of failing verification forever.
    """
    resolved = containment_target(command, spec)
    if resolved is None:
        return None
    scope, target, control = resolved
    from .containment import containment_service

    switch = await containment_service.activate(
        scope=scope,  # type: ignore[arg-type]
        target=target,
        control=control,
        actor_id=command.requested_by,
        reason=command.reason,
        blast_radius=command.blast_radius,
    )
    return switch.switch_id


async def execute(
    command: CommandRequest, spec: CommandSpec, *, attempt: int = 1
) -> CommandExecution:
    """Run one command and record what the handler actually returned.

    The execution record is *not* a verdict. ``error`` being ``None`` means the
    call returned, and nothing more; deciding whether the system reached the
    intended state is :mod:`services.kyber.ops.verification`'s job, and it needs
    ``result["handler_result"]`` intact to do it.

    A resolution or binding failure is recorded as an error on the execution
    rather than raised, so the command's history shows the attempt. The
    exception is re-raised nowhere: an operator needs to see that the handler is
    broken, not to have their request disappear.
    """
    execution = CommandExecution(command_id=command.command_id, attempt=attempt)
    side_effects: list[str] = []

    try:
        resolved = resolve_handler(spec.handler)
        call = build_call(command, spec)
        _bind(resolved, call)
    except CommandDispatchError as exc:
        execution.error = str(exc)
        execution.completed_at = now_iso()
        execution.result = {"handler": spec.handler, "resolved": False}
        logger.error(f"kyber: command {command.command_id} could not dispatch: {exc}")
        return execution

    try:
        raw = await _call(resolved, call)
    except Exception as exc:
        execution.error = f"{type(exc).__name__}: {exc}"
        execution.completed_at = now_iso()
        execution.result = {"handler": resolved.path, "resolved": True, "called": True}
        logger.error(f"kyber: command {command.command_id} handler raised: {exc}")
        return execution

    side_effects.append(f"{resolved.path}(...)")

    if "record_containment_switch" in call.follow_up:
        try:
            switch_id = await _record_containment_switch(command, spec)
        except Exception as exc:
            # The primary side effect already happened. Failing the whole
            # execution now would misreport the kill switch as un-thrown, so the
            # follow-up failure is recorded and left for verification to catch
            # through `containment_switch_active`.
            execution.error = f"follow_up_failed: {type(exc).__name__}: {exc}"
            logger.error(
                f"kyber: command {command.command_id} follow-up containment "
                f"switch failed: {exc}"
            )
        else:
            if switch_id:
                side_effects.append(f"containment_switch:{switch_id}")

    execution.result = {
        "handler": resolved.path,
        "resolved": True,
        "called": True,
        "handler_result": _normalise(raw),
    }
    execution.side_effects = side_effects
    execution.completed_at = now_iso()
    logger.info(
        f"kyber: command {command.command_id} ({command.command_type}) dispatched "
        f"to {resolved.path}"
    )
    return execution


def _normalise(raw: Any) -> Any:
    """Keep the handler's return value inspectable without reshaping it.

    Mappings pass through unchanged, because verification reads their keys.
    Pydantic models are dumped. Anything else is wrapped rather than dropped:
    an unexpected return type is information, and discarding it would leave the
    verifier with nothing to be inconclusive *about*.
    """
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (list, tuple)):
        return [_normalise(item) for item in raw]
    if isinstance(raw, (str, int, float, bool)):
        return raw
    return {"type": type(raw).__name__, "repr": repr(raw)}


__all__ = [
    "FLEET_TENANT",
    "CommandDispatchError",
    "HandlerCall",
    "ResolvedHandler",
    "build_call",
    "containment_target",
    "execute",
    "plan",
    "reset_handler_instances",
    "resolve_handler",
    "set_handler_instance",
]
