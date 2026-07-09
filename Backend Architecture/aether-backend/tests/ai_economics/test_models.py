"""Contract validation for the AI execution Pydantic mirrors."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("AETHER_ENV", "local")

from services.economic.ai_models import (  # noqa: E402
    AIInvocationObserved,
    AIPriceCard,
    BANNED_CONTENT_KEYS,
)
from ai_economics.factories import observed_payload  # noqa: E402


class TestInvocationValidation:
    def test_valid_payload_accepted(self):
        observed = AIInvocationObserved.model_validate(observed_payload())
        assert observed.status == "succeeded"
        assert observed.usage_present() is True

    @pytest.mark.parametrize("field", [
        "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens",
        "embedding_tokens", "image_units", "audio_seconds", "video_seconds",
        "tool_call_count", "retrieval_count", "latency_ms", "time_to_first_token_ms",
        "retry_count", "estimated_cost", "actual_cost", "billed_cost",
    ])
    def test_negative_usage_cost_latency_rejected(self, field):
        with pytest.raises(ValidationError):
            AIInvocationObserved.model_validate(observed_payload(**{field: -1}))

    @pytest.mark.parametrize("value,ok", [(0.0, True), (1.0, True), (1.01, False), (-0.1, False)])
    def test_quality_score_bounds(self, value, ok):
        payload = observed_payload(quality_score=value)
        if ok:
            assert AIInvocationObserved.model_validate(payload).quality_score == value
        else:
            with pytest.raises(ValidationError):
                AIInvocationObserved.model_validate(payload)

    @pytest.mark.parametrize("field", ["provider", "model", "task_type"])
    @pytest.mark.parametrize("bad", ["", "   "])
    def test_blank_required_strings_rejected(self, field, bad):
        with pytest.raises(ValidationError):
            AIInvocationObserved.model_validate(observed_payload(**{field: bad}))

    @pytest.mark.parametrize("field", ["task_type", "use_case", "business_unit"])
    def test_free_text_bounded(self, field):
        with pytest.raises(ValidationError):
            AIInvocationObserved.model_validate(observed_payload(**{field: "x" * 257}))

    def test_contains_flags_default_false(self):
        observed = AIInvocationObserved.model_validate(observed_payload())
        assert observed.contains_prompt_content is False
        assert observed.contains_completion_content is False

    def test_unknown_status_rejected(self):
        with pytest.raises(ValidationError):
            AIInvocationObserved.model_validate(observed_payload(status="partial_success"))


class TestPromptContentRejection:
    @pytest.mark.parametrize("banned", sorted(BANNED_CONTENT_KEYS))
    def test_banned_key_top_level_rejected(self, banned):
        with pytest.raises((ValidationError, ValueError)):
            AIInvocationObserved.model_validate(observed_payload(**{banned: "raw content"}))

    def test_banned_key_nested_rejected(self):
        payload = observed_payload()
        payload["provenance"] = dict(payload["provenance"], prompt_text="system: you are…")
        with pytest.raises((ValidationError, ValueError)):
            AIInvocationObserved.model_validate(payload)

    def test_banned_key_deeply_nested_rejected(self):
        payload = observed_payload()
        payload["metadata"] = {"debug": [{"messages": ["hi"]}]}
        with pytest.raises((ValidationError, ValueError)):
            AIInvocationObserved.model_validate(payload)


class TestPriceCardValidation:
    def _card(self, **overrides):
        base = {
            "id": "pc-test",
            "provider": "prov",
            "model": "model",
            "currency": "USD",
            "pricing_version": "v1",
            "rates": {"input_tokens_per_1k": 0.001},
            "effective_from": "2026-01-01T00:00:00+00:00",
            "source": "test",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        base.update(overrides)
        return base

    def test_valid_card(self):
        assert AIPriceCard.model_validate(self._card()).provider == "prov"

    def test_inverted_effective_window_rejected(self):
        with pytest.raises(ValidationError):
            AIPriceCard.model_validate(self._card(
                effective_from="2026-02-01T00:00:00+00:00",
                effective_to="2026-01-01T00:00:00+00:00",
            ))

    def test_negative_rate_rejected(self):
        with pytest.raises(ValidationError):
            AIPriceCard.model_validate(self._card(rates={"output_tokens_per_1k": -0.5}))
