"""Provider ingress cannot start without a canonical outbox relay in release envs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.settings import Environment
from connectors.provider_runtime.outbox_guard import validate_provider_outbox_delivery


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def _settings(*, env: Environment, provider: bool, relay: bool, scheduled: bool = False):
    return SimpleNamespace(
        env=env,
        provider_runtime=SimpleNamespace(
            enabled=provider,
            provider_sync_scheduler_enabled=scheduled,
        ),
        ingestion_v2=SimpleNamespace(outbox_relay_enabled=relay),
    )


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_release_env_fails_closed_when_provider_ingress_lacks_relay(env):
    with pytest.raises(RuntimeError, match="OUTBOX_RELAY_ENABLED is false"):
        validate_provider_outbox_delivery(
            _settings(env=env, provider=True, relay=False)
        )


@pytest.mark.parametrize("env", [Environment.LOCAL, Environment.DEV, Environment.INTEGRATION])
def test_non_release_env_warns_but_allows_manual_relay(env):
    logger = _Logger()
    validate_provider_outbox_delivery(
        _settings(env=env, provider=True, relay=False), logger=logger
    )
    assert len(logger.warnings) == 1
    assert "event_outbox" in logger.warnings[0]


def test_relay_enabled_or_provider_runtime_disabled_needs_no_warning():
    logger = _Logger()
    validate_provider_outbox_delivery(
        _settings(env=Environment.PRODUCTION, provider=True, relay=True), logger=logger
    )
    validate_provider_outbox_delivery(
        _settings(env=Environment.PRODUCTION, provider=False, relay=False, scheduled=True),
        logger=logger,
    )
    assert logger.warnings == []
