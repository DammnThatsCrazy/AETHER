"""Response-parsing + retry branches of ``ProductionModelProvider``.

These cover ``_request_completion`` / ``_validated_result`` / ``classify`` end to
end against a FAKE Anthropic client (``_get_client`` is monkeypatched), so no
network is touched. Every fail-closed contract is asserted directly:

* ``stop_reason == 'refusal'``  -> first-class ABSTENTION (``provider_refused``),
  nothing raised.
* ``stop_reason == 'max_tokens'`` -> :class:`ProviderResponseError`
  (``truncated_response...``) so nothing downstream is persisted.
* a response with no text block -> :class:`ProviderResponseError`
  (``empty_response...``).
* a valid JSON verdict -> a non-abstained result whose ``model_version`` carries
  the ACTUAL served-model provenance (not the pinned alias).
* transient ``anthropic.APIConnectionError`` / ``APIStatusError`` after the
  client's bounded retries -> first-class abstention
  (``provider_unavailable:...``), NEVER keyword output.

Written for the ASYNC provider form (rank3-async-provider): the fake client's
``messages.create`` is awaitable and ``classify`` is awaited via ``_classify``.
That helper also tolerates the current synchronous form, so the suite is green
both before and after the async conversion lands (see integration note in the
task record).
"""

from __future__ import annotations

import inspect
import json

import anthropic
import httpx
import pytest

from services.semantic_intelligence.providers import (
    ProductionModelProvider,
    ProviderResponseError,
    SemanticClassificationRequest,
)


# ── fake Anthropic client ────────────────────────────────────────────────────


class _TextBlock:
    """A ``content`` block the provider treats as the JSON verdict (type text)."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _ThinkingBlock:
    """A non-text ``content`` block the text-extractor must skip over."""

    def __init__(self, thinking: str = "reasoning") -> None:
        self.type = "thinking"
        self.thinking = thinking


class _FakeResponse:
    """Crafted ``messages.create`` return value.

    It is awaitable (``await`` yields itself) so the SAME object serves the async
    provider form (``await client.messages.create(...)``) and the synchronous
    form (the object is used directly), keeping the fake identical across the
    rank3 async conversion.
    """

    def __init__(
        self,
        *,
        stop_reason: str | None = None,
        content: list | None = None,
        model: str | None = "served-model-1.0",
    ) -> None:
        self.stop_reason = stop_reason
        self.content = list(content or [])
        self.model = model

    def __await__(self):
        yield from ()
        return self


class _FakeMessages:
    def __init__(self, *, response: _FakeResponse | None = None, error: BaseException | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        # Sync callable that either raises (transport failure surfaced after the
        # real client would have exhausted retries) or returns the awaitable
        # crafted response. Raising synchronously propagates in both provider
        # forms (`await create(...)` re-raises the call-time error).
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, *, response: _FakeResponse | None = None, error: BaseException | None = None) -> None:
        self.messages = _FakeMessages(response=response, error=error)


def _make_provider(fake: _FakeClient) -> ProductionModelProvider:
    """Provider with fake endpoint+api_key (so ``available()`` is True) whose
    client is the supplied fake."""
    provider = ProductionModelProvider(
        endpoint="https://model.invalid",
        api_key="test-api-key",
    )
    provider._get_client = lambda: fake  # type: ignore[method-assign]
    return provider


def _request() -> SemanticClassificationRequest:
    return SemanticClassificationRequest(
        tenant_id="tenant-1",
        source_event_id="evt-1",
        text="I really want to buy this plan.",
        language="en",
    )


async def _classify(provider: ProductionModelProvider, request: SemanticClassificationRequest):
    """Await ``classify`` whether it is async (rank3) or still synchronous."""
    result = provider.classify(request)
    if inspect.isawaitable(result):
        result = await result
    return result


# ── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_available_true_with_endpoint_and_key() -> None:
    provider = _make_provider(_FakeClient(response=_FakeResponse()))
    assert provider.available() is True


@pytest.mark.asyncio
async def test_refusal_stop_reason_abstains_without_raising() -> None:
    fake = _FakeClient(response=_FakeResponse(stop_reason="refusal", content=[]))
    provider = _make_provider(fake)

    result = await _classify(provider, _request())

    assert result.abstained is True
    assert result.abstention_reason == "provider_refused"
    assert result.stance is None
    assert result.intent is None
    assert result.speech_act is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_max_tokens_stop_reason_raises_truncated() -> None:
    # Truncated JSON must be rejected as truncation (never persisted downstream),
    # not silently parsed into a confusing malformed_json error.
    fake = _FakeClient(
        response=_FakeResponse(
            stop_reason="max_tokens",
            content=[_TextBlock('{"stance": "supportive"')],
        )
    )
    provider = _make_provider(fake)

    with pytest.raises(ProviderResponseError) as excinfo:
        await _classify(provider, _request())
    assert str(excinfo.value).startswith("truncated_response")


@pytest.mark.asyncio
async def test_no_text_block_raises_empty_response() -> None:
    fake = _FakeClient(
        response=_FakeResponse(stop_reason="end_turn", content=[_ThinkingBlock()])
    )
    provider = _make_provider(fake)

    with pytest.raises(ProviderResponseError) as excinfo:
        await _classify(provider, _request())
    assert str(excinfo.value).startswith("empty_response")


@pytest.mark.asyncio
async def test_valid_verdict_returns_result_with_served_model_provenance() -> None:
    verdict = {
        "stance": "supportive",
        "intent": "purchase",
        "speech_act": "statement",
        # duplicates / mixed case / padding are normalized+deduped by the provider
        "topics": ["billing", "Billing", "  refund "],
        "valence": 0.5,
        "confidence": 0.9,
    }
    fake = _FakeClient(
        response=_FakeResponse(
            stop_reason="end_turn",
            content=[_TextBlock(json.dumps(verdict))],
            model="served-model-2026-08",
        )
    )
    provider = _make_provider(fake)

    result = await _classify(provider, _request())

    assert result.abstained is False
    assert result.abstention_reason is None
    assert result.stance == "supportive"
    assert result.intent == "purchase"
    assert result.speech_act == "statement"
    assert result.topics == ("billing", "refund")
    assert result.valence == 0.5
    assert result.confidence == 0.9
    # Provenance is the ACTUAL serving model from the response, not the pinned id.
    assert result.model_version == "served-model-2026-08"
    assert result.model_id == provider._model_id
    assert result.provider == provider.name


@pytest.mark.asyncio
async def test_api_connection_error_becomes_first_class_abstention() -> None:
    request = httpx.Request("POST", "https://model.invalid/v1/messages")
    error = anthropic.APIConnectionError(request=request)
    provider = _make_provider(_FakeClient(error=error))

    result = await _classify(provider, _request())

    assert result.abstained is True
    assert result.abstention_reason is not None
    assert result.abstention_reason.startswith("provider_unavailable")
    assert "APIConnectionError" in result.abstention_reason
    # Fail closed: NOT degraded to keyword output.
    assert result.stance is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_api_status_error_becomes_first_class_abstention() -> None:
    request = httpx.Request("POST", "https://model.invalid/v1/messages")
    response = httpx.Response(503, request=request)
    error = anthropic.APIStatusError("service unavailable", response=response, body=None)
    provider = _make_provider(_FakeClient(error=error))

    result = await _classify(provider, _request())

    assert result.abstained is True
    assert result.abstention_reason is not None
    assert result.abstention_reason.startswith("provider_unavailable")
    assert "APIStatusError" in result.abstention_reason
    assert result.stance is None
