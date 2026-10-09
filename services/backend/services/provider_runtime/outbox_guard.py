"""Startup coherence check for provider canonical outbox delivery."""

from __future__ import annotations

from config.settings import Environment


def validate_provider_outbox_delivery(settings, *, logger=None) -> None:
    """Require a relay when provider ingress can enqueue canonical events.

    The provider runtime master flag mounts authenticated sync and verified
    webhook ingress; the scheduled pull flag only adds a background producer.
    Staging/production must not accept provider ingress while its canonical
    event outbox has no relay. Local/dev may intentionally drain it by hand.
    """
    if not settings.provider_runtime.enabled or settings.ingestion_v2.outbox_relay_enabled:
        return
    message = (
        "AETHER_PROVIDER_RUNTIME_ENABLED is true but OUTBOX_RELAY_ENABLED is false: "
        "provider canonical events will remain pending in event_outbox. "
        "Start an outbox-relay role before enabling provider ingress."
    )
    if settings.env in (Environment.STAGING, Environment.PRODUCTION):
        raise RuntimeError(f"fail-closed: {message}")
    if logger is not None:
        logger.warning(message)


__all__ = ["validate_provider_outbox_delivery"]
