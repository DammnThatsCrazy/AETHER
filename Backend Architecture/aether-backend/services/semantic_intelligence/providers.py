"""Semantic classifier provider abstraction.

Text classification runs behind a pluggable provider so production model backends
can be swapped in without touching the pipeline. Every provider implements
``classify()`` for real — there is no silent keyword fallback behind a
production label. The factory FAILS CLOSED: when configured for a
production/multilingual model but credentials are absent it returns
:class:`DisabledProvider` carrying ``credential_waiting`` (which abstains) —
never a keyword fallback masquerading as the production model. The
deterministic provider (tool-less, no network) remains the default for CI,
replay and structured events, and is the ONLY provider whose output comes from
the keyword classifier.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic

from .models import IntentLabel, SpeechAct, StanceLabel, utc_now

# Configuration state recorded on abstentions when a model-backed mode is
# selected but no credentials exist (this environment, pre-staging).
CREDENTIAL_WAITING = "credential_waiting"

# Model id pinned from config (env), never guessed at request time.
_DEFAULT_MODEL_ID = "claude-opus-5"
_MAX_TOPICS = 16
_MAX_TOPIC_LENGTH = 64

_STANCE_VALUES = frozenset(v.value for v in StanceLabel)
_INTENT_VALUES = frozenset(v.value for v in IntentLabel)
_SPEECH_ACT_VALUES = frozenset(v.value for v in SpeechAct)
_RESPONSE_FIELDS = frozenset(
    {"stance", "intent", "speech_act", "topics", "valence", "confidence"}
)

_SYSTEM_PROMPT = (
    "You classify one customer/agent text into a strict JSON verdict for a "
    "semantic-intelligence pipeline. Return ONLY a JSON object with exactly "
    "these fields: stance, intent, speech_act, topics (array of short "
    "lowercase strings), valence (number in [-1, 1], or null when no sentiment "
    "is expressed) and confidence (number in [0, 1]). Use only the allowed "
    "enum values for stance, intent and speech_act."
)


class ProviderResponseError(RuntimeError):
    """A model backend returned output violating the classification contract.

    Raised on malformed JSON, unknown labels, missing/unexpected fields or
    out-of-range scores. Fail closed: callers must REJECT the response —
    nothing derived from it may be persisted (never partially ingest).
    """


class _ProviderRefusal(Exception):
    """Internal: the model declined to classify (``stop_reason == 'refusal'``)."""


def provider_identity(name: str) -> tuple[str, str]:
    """Split a provider name ('id@version') into (model_id, model_version).

    A name without '@' keeps the full name as model_id with version '0' so the
    provenance stays distinguishable from the deterministic defaults.
    """
    model_id, sep, model_version = name.partition("@")
    return (model_id, model_version) if sep else (name, "0")


@dataclass(frozen=True)
class SemanticClassificationRequest:
    """Input handed to a provider: the eligible text plus routing context."""

    tenant_id: str
    source_event_id: str
    text: str
    language: str = "en"


@dataclass(frozen=True)
class SemanticClassificationResult:
    """A provider's verdict — a classification or a first-class abstention.

    ``model_id``/``model_version`` are the ACTUAL identity of whatever produced
    the labels (observation provenance stamps come from here, never from a
    static alias) and ``classified_at`` timestamps the verdict.
    """

    provider: str
    model_id: str
    model_version: str
    abstained: bool
    abstention_reason: str | None
    stance: str | None
    intent: str | None
    speech_act: str | None
    topics: tuple[str, ...]
    valence: float | None
    confidence: float
    classified_at: datetime = field(default_factory=utc_now)

    @classmethod
    def abstain(cls, provider_name: str, reason: str) -> "SemanticClassificationResult":
        """First-class abstention: recorded state, not an error."""
        model_id, model_version = provider_identity(provider_name)
        return cls(
            provider=provider_name,
            model_id=model_id,
            model_version=model_version,
            abstained=True,
            abstention_reason=reason,
            stance=None,
            intent=None,
            speech_act=None,
            topics=(),
            valence=None,
            confidence=0.0,
        )


class SemanticClassifierProvider(ABC):
    """A text-classification backend. Tool-less: no execution authority."""

    name: str = "abstract"

    @abstractmethod
    def available(self) -> bool:
        """True when this provider can classify text right now."""

    @abstractmethod
    def classify(self, request: SemanticClassificationRequest) -> SemanticClassificationResult:
        """Classify eligible text, or return a first-class abstention.

        Raises :class:`ProviderResponseError` when the backend's response
        violates the contract — the caller must persist nothing derived from it.
        """

    def abstention_reason(self) -> str | None:
        return None


class DeterministicClassifierProvider(SemanticClassifierProvider):
    """Keyword/structured deterministic classifier — the CI/replay default.

    The ONLY provider whose verdicts come from the keyword classifier; its
    results are always stamped with this explicitly-deterministic identity.
    """

    name = "deterministic-semantic-classifier@1.0.0"

    def available(self) -> bool:
        return True

    def classify(self, request: SemanticClassificationRequest) -> SemanticClassificationResult:
        # Function-level import: the engine imports this module at load time,
        # so the keyword derivation lives in one place without an import cycle.
        from .engine import keyword_labels

        text = request.text.strip()
        if not text:
            return SemanticClassificationResult.abstain(self.name, "insufficient_content")
        labels = keyword_labels(text)
        total = labels.pos + labels.neg
        model_id, model_version = provider_identity(self.name)
        return SemanticClassificationResult(
            provider=self.name,
            model_id=model_id,
            model_version=model_version,
            abstained=False,
            abstention_reason=None,
            stance=labels.stance.value,
            intent=labels.intent.value,
            speech_act=labels.speech.value,
            topics=tuple(labels.topics),
            valence=((labels.pos - labels.neg) / total) if total else None,
            confidence=0.85,
        )


class DisabledProvider(SemanticClassifierProvider):
    """Fail-closed provider: always unavailable, always abstains."""

    name = "disabled"

    def __init__(self, reason: str = "provider_disabled") -> None:
        self._reason = reason

    def available(self) -> bool:
        return False

    def classify(self, request: SemanticClassificationRequest) -> SemanticClassificationResult:
        return SemanticClassificationResult.abstain(self.name, self._reason)

    def abstention_reason(self) -> str | None:
        return self._reason


def _response_schema() -> dict[str, Any]:
    """JSON schema the model output must satisfy (also enforced client-side)."""
    return {
        "type": "object",
        "properties": {
            "stance": {"type": "string", "enum": sorted(_STANCE_VALUES)},
            "intent": {"type": "string", "enum": sorted(_INTENT_VALUES)},
            "speech_act": {"type": "string", "enum": sorted(_SPEECH_ACT_VALUES)},
            "topics": {"type": "array", "items": {"type": "string"}},
            "valence": {"type": ["number", "null"]},
            "confidence": {"type": "number"},
        },
        "required": sorted(_RESPONSE_FIELDS),
        "additionalProperties": False,
    }


class ProductionModelProvider(SemanticClassifierProvider):
    """Real network model backend over the Anthropic client.

    Constructed by the factory only when credentials are present; ``classify``
    still re-checks and abstains with ``credential_waiting`` rather than ever
    guessing. The client carries an explicit timeout and bounded retries with
    exponential backoff; output size is capped; the model id is pinned from
    config, never inferred per request. Responses are schema-validated and any
    contract violation is REJECTED wholesale via :class:`ProviderResponseError`
    — a malformed response is never partially ingested. Transport failures
    after retries become first-class abstentions, never keyword output.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        multilingual: bool = False,
        model_id: str | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._model_id = model_id or os.getenv("SEMANTIC_MODEL_ID", _DEFAULT_MODEL_ID)
        self._timeout_seconds = float(os.getenv("SEMANTIC_MODEL_TIMEOUT_SECONDS", "10"))
        self._max_retries = int(os.getenv("SEMANTIC_MODEL_MAX_RETRIES", "2"))
        self._max_output_tokens = int(os.getenv("SEMANTIC_MODEL_MAX_OUTPUT_TOKENS", "512"))
        self._client: anthropic.Anthropic | None = None
        self.name = (
            "multilingual-semantic-model@1.0.0"
            if multilingual
            else "production-semantic-model@1.0.0"
        )

    def available(self) -> bool:
        return bool(self._endpoint and self._api_key)

    def classify(self, request: SemanticClassificationRequest) -> SemanticClassificationResult:
        if not self.available():
            # Missing credentials are configuration state, not an error: abstain
            # and record that the provider is waiting on credentials.
            return SemanticClassificationResult.abstain(self.name, CREDENTIAL_WAITING)
        try:
            raw, served_model = self._request_completion(request)
        except _ProviderRefusal:
            return SemanticClassificationResult.abstain(self.name, "provider_refused")
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            # Transport/API failure after bounded retries: fail closed to a
            # first-class abstention — never degrade to the keyword classifier.
            return SemanticClassificationResult.abstain(
                self.name, f"provider_unavailable:{type(exc).__name__}"
            )
        return self._validated_result(raw, served_model)

    # ── network + validation ────────────────────────────────────────────────

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                base_url=self._endpoint,
                timeout=self._timeout_seconds,
                max_retries=self._max_retries,
            )
        return self._client

    def _request_completion(self, request: SemanticClassificationRequest) -> tuple[str, str]:
        """One inference round-trip → (raw JSON text, actual serving model id)."""
        response = self._get_client().messages.create(
            model=self._model_id,
            max_tokens=self._max_output_tokens,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"language: {request.language}\ntext:\n{request.text}",
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": _response_schema()}},
        )
        if getattr(response, "stop_reason", None) == "refusal":
            raise _ProviderRefusal()
        text = next(
            (
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            ),
            None,
        )
        if text is None:
            raise ProviderResponseError("empty_response: no text block in model response")
        return text, str(getattr(response, "model", None) or self._model_id)

    def _validated_result(self, raw: str, served_model: str) -> SemanticClassificationResult:
        """Validate the full response contract; REJECT on any violation."""
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ProviderResponseError(f"malformed_json: {exc}") from None
        if not isinstance(data, dict):
            raise ProviderResponseError("malformed_response: expected a JSON object")
        missing = _RESPONSE_FIELDS - data.keys()
        unexpected = data.keys() - _RESPONSE_FIELDS
        if missing or unexpected:
            raise ProviderResponseError(
                f"schema_violation: missing={sorted(missing)} unexpected={sorted(unexpected)}"
            )
        stance, intent, speech_act = data["stance"], data["intent"], data["speech_act"]
        if stance not in _STANCE_VALUES:
            raise ProviderResponseError(f"schema_violation: unknown stance {stance!r}")
        if intent not in _INTENT_VALUES:
            raise ProviderResponseError(f"schema_violation: unknown intent {intent!r}")
        if speech_act not in _SPEECH_ACT_VALUES:
            raise ProviderResponseError(f"schema_violation: unknown speech_act {speech_act!r}")
        topics = data["topics"]
        if (
            not isinstance(topics, list)
            or len(topics) > _MAX_TOPICS
            or any(
                not isinstance(t, str) or not t.strip() or len(t) > _MAX_TOPIC_LENGTH
                for t in topics
            )
        ):
            raise ProviderResponseError("schema_violation: invalid topics")
        confidence = data["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= confidence <= 1.0
        ):
            raise ProviderResponseError(
                f"schema_violation: confidence out of range: {confidence!r}"
            )
        valence = data["valence"]
        if valence is not None and (
            isinstance(valence, bool)
            or not isinstance(valence, (int, float))
            or not -1.0 <= valence <= 1.0
        ):
            raise ProviderResponseError(f"schema_violation: valence out of range: {valence!r}")
        return SemanticClassificationResult(
            provider=self.name,
            model_id=self._model_id,
            model_version=served_model,
            abstained=False,
            abstention_reason=None,
            stance=stance,
            intent=intent,
            speech_act=speech_act,
            topics=tuple(dict.fromkeys(t.strip().lower() for t in topics)),
            valence=float(valence) if valence is not None else None,
            confidence=float(confidence),
        )


def get_classifier_provider(
    settings, tenant_id: str | None = None
) -> SemanticClassifierProvider:
    """Resolve the configured provider, failing closed without credentials.

    Canary routing: a tenant listed in ``semantic.canary_tenants`` resolves the
    candidate (production) provider instead of the primary — with exactly the
    same fail-closed behavior, so a credential-less canary abstains via
    :class:`DisabledProvider` rather than degrading to keywords. Every other
    tenant (and any call without a tenant) keeps the primary provider.
    """
    semantic = getattr(settings, "semantic", None)
    if tenant_id is not None and tenant_id in (getattr(semantic, "canary_tenants", None) or []):
        return _resolve_mode("production")
    return _resolve_mode((getattr(semantic, "classifier_provider", "") or "").lower())


def get_shadow_provider(settings) -> SemanticClassifierProvider | None:
    """Resolve the shadow-mode candidate provider, or None when shadow is off.

    ``semantic.shadow_provider`` names a provider mode ('' = off). The candidate
    resolves through the same fail-closed ladder as the primary; a candidate
    without credentials resolves to :class:`DisabledProvider` (it abstains in
    the comparison — it never fabricates a shadow classification).
    """
    mode = (getattr(getattr(settings, "semantic", None), "shadow_provider", "") or "").lower()
    if not mode:
        return None
    return _resolve_mode(mode)


def _resolve_mode(mode: str) -> SemanticClassifierProvider:
    """Shared fail-closed mode ladder for primary, canary and shadow resolution."""
    if mode in ("", "deterministic"):
        return DeterministicClassifierProvider()
    if mode == "disabled":
        return DisabledProvider("provider_disabled_by_config")
    if mode in ("production", "multilingual"):
        endpoint = os.getenv("SEMANTIC_MODEL_ENDPOINT", "")
        api_key = os.getenv("SEMANTIC_MODEL_API_KEY", "")
        if not (endpoint and api_key):
            # FAIL CLOSED — never silently degrade a production request to
            # keywords; the abstention records the configuration state.
            return DisabledProvider(CREDENTIAL_WAITING)
        return ProductionModelProvider(endpoint, api_key, multilingual=(mode == "multilingual"))
    return DisabledProvider(f"provider_disabled_unknown_mode:{mode}")
