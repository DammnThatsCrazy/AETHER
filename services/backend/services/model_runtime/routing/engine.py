"""AETHER model-runtime routing engine — model selection per routing mode.

Implements ADR-008 D4. The router selects a model for a request according to
one of four modes:

* ``auto`` — the harness picks the best model for the task from the registry
  (preferring ``recommended`` then ``stable`` status, in deterministic registry
  order), filtered by the request's entitlement allowlist when present.
* ``tenant_default`` — the tenant-configured default model.
* ``explicit`` — the operator/tenant requests a specific model id.
* ``policy_required`` — a policy mandates a specific model (strict).

The request's ``entitled_model_ids`` allowlist is a pre-filter that applies to
EVERY mode at the routing entry point (not only ``auto``): a target model
outside the allowlist falls back (or raises for the strict ``policy_required``
mode) exactly like an entitlement denial.

Every route is subject to entitlement checks. When the requested route is
unavailable, misconfigured, or not entitled, the router engages a fallback
chain and records the decision (``fallback=True`` + reason) on the returned
``RouteSelection``. ``policy_required`` is strict: a denied or unmandated
policy route raises ``RoutingPolicyViolation`` / ``RoutingUnavailable`` rather
than silently routing elsewhere.

Registry providers that are OpenAI-compatible but not members of the
``ModelProvider`` enum (``kimi`` / ``deepseek`` / ``qwen``) are preserved:
routing resolves them to the compatible-adapter classification
(``ModelProvider.OPENAI``) instead of silently substituting the router's
default provider, and carries the registry-declared provider key
(``registry_provider``) on the returned ``RouteSelection`` so the runtime can
look up the *registered* provider (``kimi`` / ``deepseek`` / ``qwen``) rather
than the collapsed ``openai`` name.

Security: this module never logs, returns, or exposes tenant PII or
credentials — it carries only model ids. The server is authoritative for
tenant scope; a routing decision can never widen or override tenant scope.
The engine is deterministic — no randomness, no wall-clock-dependent choice.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Mapping, Sequence

from services.model_runtime.models import ModelProvider
from services.model_runtime.routing.models import (
    RoutingMode,
    RoutingNotEntitled,
    RoutingPolicyViolation,
    RoutingRequest,
    RoutingUnavailable,
    RouteSelection,
)
from shared.model_governance.generated_model_registry import MODEL_REGISTRY_MODELS
from shared.model_governance.generated_task_profiles import TASK_PROFILES

if TYPE_CHECKING:
    from services.model_runtime.routing.entitlements import EntitlementResolver
    from services.model_runtime.routing.fallback import FallbackChain

# Status ordering for auto routing: recommended beats stable beats everything.
_STATUS_PRIORITY: Mapping[str, int] = {"recommended": 0, "stable": 1}

# Registry providers that are OpenAI-compatible but NOT members of the
# ModelProvider enum (kimi / deepseek / qwen). They run via
# OpenAICompatibleModelProvider (adapters/compatible.py) at invocation time;
# routing preserves the declared provider by classifying them as the compatible
# adapter (ModelProvider.OPENAI) instead of silently substituting the default.
_OPENAI_COMPATIBLE_PROVIDER_NAMES: frozenset[str] = frozenset(
    {"kimi", "deepseek", "qwen"}
)

# Profile registry default: index the generated TASK_PROFILES tuple by profileId.
_DEFAULT_PROFILE_REGISTRY: dict[str, Mapping[str, object]] = {
    str(profile["profileId"]): dict(profile) for profile in TASK_PROFILES
}

# Key a policy profile may use to mandate a specific model when the policy
# (not the request) selects the model for policy_required routing.
_POLICY_MANDATED_MODEL_KEY = "mandatedModel"


class RoutedSelection(RouteSelection):
    """A route selection that also carries the registry-declared provider key.

    ``provider`` (inherited) is the adapter classification as a
    :class:`ModelProvider` member — e.g. ``ModelProvider.OPENAI`` for the
    OpenAI-compatible (kimi/deepseek/qwen) models. ``registry_provider`` is
    the provider name as declared in the model registry (``"kimi"``,
    ``"deepseek"``, ``"qwen"``, ``"anthropic"``, ...) so the runtime can look
    up the *registered* provider instance by that key. OpenAI-compatible
    providers are registered under their own names (not ``"openai"``), so
    collapsing to the adapter classification at selection time would route
    them to the wrong (or an unconfigured) provider at invocation time.
    """

    registry_provider: str | None = None


class ModelRouter:
    """Selects a model for a routing request and records the route/fallback.

    ``entitlements`` is the authoritative ``EntitlementResolver``; the router
    never second-guesses a denial. ``registry_models`` defaults to the
    generated model registry, ``profile_registry`` to the generated
    ``TASK_PROFILES`` index (keyed by ``profileId``). ``fallback`` is an
    optional ``FallbackChain``; when ``None`` the router lazily builds a
    registry-status-based chain on first fallback.
    """

    def __init__(
        self,
        entitlements: EntitlementResolver,
        *,
        registry_models: Sequence[Mapping[str, object]] | None = None,
        profile_registry: Mapping[str, Mapping[str, object]] | None = None,
        fallback: FallbackChain | None = None,
        default_provider: ModelProvider = ModelProvider.DETERMINISTIC,
    ) -> None:
        self._entitlements = entitlements
        self._fallback = fallback
        self._default_provider = default_provider

        models: Sequence[Mapping[str, object]] = (
            registry_models if registry_models is not None else MODEL_REGISTRY_MODELS
        )
        self._models: list[Mapping[str, object]] = list(models)
        self._model_index: dict[str, Mapping[str, object]] = {
            str(entry["modelId"]): entry for entry in self._models
        }

        self._profile_registry: Mapping[str, Mapping[str, object]] = (
            profile_registry if profile_registry is not None else _DEFAULT_PROFILE_REGISTRY
        )

    # ------------------------------------------------------------------ public

    async def route(self, request: RoutingRequest) -> RouteSelection:
        """Resolve a routing request to a single model selection.

        Raises ``RoutingUnavailable`` when no route can be constructed at all,
        ``RoutingPolicyViolation`` when a strict policy route is denied, and
        (from the entitlement resolver) ``RoutingNotEntitled`` on denials the
        router cannot reconcile with a fallback.
        """
        mode = self._resolve_mode(request)
        # The entitlement allowlist is a pre-filter that applies to EVERY mode
        # at the entry point — not only auto. A target model outside the
        # allowlist behaves exactly like an entitlement denial: fallback for
        # tenant_default/explicit, strict raise for policy_required.
        if request.entitled_model_ids is not None:
            target = self._primary_target(request, mode)
            if target is not None and target not in request.entitled_model_ids:
                if mode is RoutingMode.POLICY_REQUIRED:
                    raise RoutingPolicyViolation(
                        "policy-mandated model not in entitlement allowlist"
                    )
                return await self._fallback_selection(
                    request,
                    mode,
                    f"{mode.value} model not in the entitlement allowlist",
                )
        if mode is RoutingMode.AUTO:
            return await self._route_auto(request)
        if mode is RoutingMode.TENANT_DEFAULT:
            return await self._route_tenant_default(request)
        if mode is RoutingMode.EXPLICIT:
            return await self._route_explicit(request)
        return await self._route_policy_required(request)

    def describe_selection(self, sel: RouteSelection) -> str:
        """Audit-safe one-liner for a selection. No PII, no credentials.

        Carries only model id / mode / provider / entitlement / fallback.
        """
        parts = [
            f"model={sel.model_id}",
            f"mode={sel.mode.value}",
            f"provider={sel.provider.value}",
            f"entitled={'yes' if sel.entitled else 'no'}",
            f"fallback={'yes' if sel.fallback else 'no'}",
        ]
        if sel.fallback_reason:
            parts.append(f"reason={sel.fallback_reason}")
        return " | ".join(parts)

    # ------------------------------------------------------------- mode dispatch

    def _resolve_mode(self, request: RoutingRequest) -> RoutingMode:
        if request.mode is not None:
            return request.mode
        profile = self._profile_for(request.profile_id)
        if profile is not None:
            default = profile.get("defaultRoutingMode")
            if default is not None:
                try:
                    return RoutingMode(str(default))
                except ValueError as exc:
                    raise RoutingUnavailable(
                        f"profile default routing mode is invalid: {default!r}"
                    ) from exc
        return RoutingMode.AUTO

    def _primary_target(
        self, request: RoutingRequest, mode: RoutingMode
    ) -> str | None:
        """The model id a non-auto mode intends to route, before fallback logic.

        ``None`` means the mode derives its target inside its own handler:
        ``auto`` filters candidates against the allowlist itself, and
        ``policy_required`` may take the profile-mandated model. The entry-point
        allowlist gate uses this to pre-filter the other modes uniformly.
        """
        if mode is RoutingMode.TENANT_DEFAULT:
            return request.tenant_default_model
        if mode is RoutingMode.EXPLICIT:
            return request.requested_model
        if mode is RoutingMode.POLICY_REQUIRED:
            if request.requested_model:
                return request.requested_model
            profile = self._profile_for(request.profile_id)
            if profile is not None:
                mandated = profile.get(_POLICY_MANDATED_MODEL_KEY)
                return str(mandated) if mandated else None
            return None
        return None  # AUTO filters candidates inside _route_auto

    # -------------------------------------------------------------- route modes

    async def _route_auto(self, request: RoutingRequest) -> RouteSelection:
        candidates = list(self._models)
        if request.entitled_model_ids is not None:
            allow = request.entitled_model_ids
            candidates = [
                entry for entry in candidates if entry.get("modelId") in allow
            ]
        if not candidates:
            raise RoutingUnavailable("no eligible models in registry for auto routing")

        ordered = sorted(
            enumerate(candidates),
            key=lambda pair: (_STATUS_PRIORITY.get(str(pair[1].get("status", "")), 99), pair[0]),
        )

        # Automatic routing searches the FULL ordered candidate list for the
        # best entitled model. Testing only ``ordered[0]`` and then handing a
        # denial to the RegistryFallbackChain (which inspects only its first
        # few registry candidates) would fail closed with "no entitled fallback
        # route" for a tenant entitled solely to a later recommended/stable
        # model even though an eligible model exists. Only when NO ordered
        # candidate is entitled does the router engage the fallback chain.
        for pos, (_, entry) in enumerate(ordered):
            model_id = str(entry["modelId"])
            if not await self._is_entitled(request.tenant_id, model_id):
                continue
            is_best = pos == 0
            return self._selection(
                model_id,
                RoutingMode.AUTO,
                fallback=not is_best,
                fallback_reason=(
                    None if is_best else "best auto model not entitled for tenant"
                ),
            )
        return await self._fallback_selection(
            request, RoutingMode.AUTO, "best auto model not entitled for tenant"
        )

    async def _route_tenant_default(self, request: RoutingRequest) -> RouteSelection:
        model_id = request.tenant_default_model
        if not model_id:
            return await self._fallback_selection(
                request, RoutingMode.TENANT_DEFAULT, "tenant default model not configured"
            )
        if model_id not in self._model_index:
            return await self._fallback_selection(
                request, RoutingMode.TENANT_DEFAULT, "tenant default model unavailable in registry"
            )
        if not await self._is_entitled(request.tenant_id, model_id):
            return await self._fallback_selection(
                request, RoutingMode.TENANT_DEFAULT, "tenant default model not entitled for tenant"
            )
        return self._selection(model_id, RoutingMode.TENANT_DEFAULT, fallback=False)

    async def _route_explicit(self, request: RoutingRequest) -> RouteSelection:
        model_id = request.requested_model
        if not model_id:
            return await self._fallback_selection(
                request, RoutingMode.EXPLICIT, "explicit routing requested no model"
            )
        if model_id not in self._model_index:
            return await self._fallback_selection(
                request, RoutingMode.EXPLICIT, "requested model unavailable in registry"
            )
        if not await self._is_entitled(request.tenant_id, model_id):
            return await self._fallback_selection(
                request, RoutingMode.EXPLICIT, "requested model not entitled for tenant"
            )
        return self._selection(model_id, RoutingMode.EXPLICIT, fallback=False)

    async def _route_policy_required(self, request: RoutingRequest) -> RouteSelection:
        profile = self._profile_for(request.profile_id)
        if profile is not None:
            allowed = profile.get("allowedRoutingModes")
            if allowed is not None and "policy_required" not in allowed:
                raise RoutingPolicyViolation(
                    "profile does not allow policy_required routing"
                )

        model_id = request.requested_model
        if not model_id and profile is not None:
            mandated = profile.get(_POLICY_MANDATED_MODEL_KEY)
            model_id = str(mandated) if mandated else None
        if not model_id:
            raise RoutingUnavailable("policy_required routing with no mandated model")
        if model_id not in self._model_index:
            raise RoutingPolicyViolation("policy-mandated model unavailable in registry")
        if not await self._is_entitled(request.tenant_id, model_id):
            raise RoutingPolicyViolation("policy-mandated model denied by entitlement")

        return self._selection(model_id, RoutingMode.POLICY_REQUIRED, fallback=False)

    # ------------------------------------------------------------- fallback

    async def _fallback_selection(
        self,
        request: RoutingRequest,
        mode: RoutingMode,
        reason: str,
        *,
        exclude: Collection[str] = (),
    ) -> RouteSelection:
        """Engage the fallback chain; raise RoutingPolicyViolation if unusable.

        ``exclude`` lists model ids already attempted (e.g. at dispatch time)
        that must never be re-selected. Combined with the request allowlist
        below, a fallback can never broaden the request's policy scope: when
        ``request.entitled_model_ids`` is present it gates every candidate, so
        a resolver-entitled model outside the request allowlist is never
        returned as a fallback.
        """
        # Lazy import so the module loads even before the sibling fallback
        # module lands; select_fallback is the Agent C contract helper.
        from services.model_runtime.routing.fallback import (
            RegistryFallbackChain,
            select_fallback,
        )

        chain = self._fallback
        if chain is None:
            chain = RegistryFallbackChain()

        entitled: set[str] = set()
        for candidate in chain.candidates():
            if candidate in exclude:
                continue
            if candidate in self._model_index and await self._is_entitled(
                request.tenant_id, candidate
            ):
                entitled.add(candidate)

        def _must_entitle(model_id: str) -> bool:
            if model_id not in entitled:
                return False
            # A fallback must never broaden the request's policy scope: an
            # allowlisted request may only fall back inside its own allowlist.
            if (
                request.entitled_model_ids is not None
                and model_id not in request.entitled_model_ids
            ):
                return False
            return True

        try:
            selected = select_fallback(
                request.requested_model or "", chain, must_entitle=_must_entitle
            )
        except Exception as exc:  # no fallback candidate passes the chain
            raise RoutingPolicyViolation(f"no entitled fallback route: {reason}") from exc
        if not selected:
            raise RoutingPolicyViolation(f"no entitled fallback route: {reason}")

        return RoutedSelection(
            model_id=selected,
            provider=self._provider_for(selected),
            registry_provider=self._registry_provider_name(selected),
            mode=mode,
            entitled=True,
            fallback=True,
            fallback_reason=reason,
        )

    async def dispatch_fallback(
        self,
        request: RoutingRequest,
        *,
        exclude: Collection[str],
        reason: str,
    ) -> RouteSelection | None:
        """Bounded runtime fallback after a dispatch-time rejection.

        Engages the same entitlement/allowlist-gated fallback chain as routing
        but skips model ids already attempted (``exclude``), so a cycle can
        never re-select a rejected model. Returns ``None`` when no eligible
        fallback exists so the runtime fails closed with the original dispatch
        error. Strict ``policy_required`` routes never dispatch-fallback (they
        are already strict at routing time).
        """
        if request.mode is RoutingMode.POLICY_REQUIRED:
            return None
        try:
            return await self._fallback_selection(
                request,
                request.mode or RoutingMode.AUTO,
                reason,
                exclude=exclude,
            )
        except RoutingPolicyViolation:
            return None

    # ------------------------------------------------------------------ helpers

    def _profile_for(self, profile_id: str | None) -> Mapping[str, object] | None:
        if not profile_id:
            return None
        return self._profile_registry.get(profile_id)

    async def _is_entitled(self, tenant_id: str, model_id: str) -> bool:
        """Ask the resolver; treat both raise-denial and decision-denial as no."""
        try:
            decision = await self._entitlements.assert_model_entitled(tenant_id, model_id)
        except RoutingNotEntitled:
            return False
        return bool(decision.entitled)

    def _selection(
        self,
        model_id: str,
        mode: RoutingMode,
        *,
        fallback: bool,
        fallback_reason: str | None = None,
    ) -> RouteSelection:
        return RoutedSelection(
            model_id=model_id,
            provider=self._provider_for(model_id),
            registry_provider=self._registry_provider_name(model_id),
            mode=mode,
            entitled=True,
            fallback=fallback,
            fallback_reason=fallback_reason,
        )

    def _registry_provider_name(self, model_id: str) -> str | None:
        """The provider name declared for ``model_id`` in the registry.

        Returns ``None`` when the registry entry carries no string provider
        (the runtime then falls back to the classification provider).
        """
        entry = self._model_index.get(model_id)
        provider_name = entry.get("provider") if entry is not None else None
        return provider_name if isinstance(provider_name, str) else None

    def _provider_for(self, model_id: str) -> ModelProvider:
        entry = self._model_index.get(model_id)
        provider_name = entry.get("provider") if entry is not None else None
        if isinstance(provider_name, str):
            if provider_name in _OPENAI_COMPATIBLE_PROVIDER_NAMES:
                # Preserve the declared provider instead of substituting the
                # default: OpenAI-compatible registry providers (kimi/deepseek/
                # qwen) resolve to the compatible adapter classification.
                return ModelProvider.OPENAI
            try:
                return ModelProvider(provider_name)
            except ValueError:
                pass
        return self._default_provider
