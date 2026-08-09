"""Normalization engine — applies a plugin's normalizer to raw records.

The engine is a thin aggregation loop over
:class:`~shared.integration_contracts.normalization.EventNormalizer` (the
plugin's ``normalizer()`` accessor). A normalizer's ``normalize(record)`` returns
a :class:`~shared.integration_contracts.normalization.NormalizationResult` per
record: ``events`` (normalized :class:`AetherEvent` list), ``skipped`` (an int
count of records the normalizer chose not to emit), ``dropped`` (a list of
ids-or-short-reasons for anything that could not be normalized — never silent),
and ``normalizer_version``.

The engine NEVER drops a record silently:

* the normalizer's own ``dropped`` reasons are aggregated verbatim;
* if the plugin exposes no ``normalizer()``, every record is dropped with the
  explicit reason ``"<record_id>:no_normalizer"`` — never silently skipped.

``run`` is synchronous (matching the :class:`EventNormalizer` protocol); the
scheduler that consumes the engine handles a sync return.
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.events import RawProviderRecord


class NormalizationEngine:
    """Applies a plugin's ``normalizer()`` to raw records, aggregates results."""

    def __init__(self, plugin) -> None:
        # plugin: services.provider_runtime.plugin.BaseProviderPlugin (Team C seam)
        self.plugin = plugin

    def _normalizer(self):
        """Resolve the plugin's normalizer accessor (None when absent)."""
        accessor = getattr(self.plugin, "normalizer", None)
        if accessor is None:
            return None
        normalizer = accessor() if callable(accessor) else accessor
        return normalizer

    def run(self, records: Iterable[RawProviderRecord]) -> NormalizationResult:
        """Normalize every record and aggregate per-record results.

        Returns a single :class:`NormalizationResult`. ``normalizer_version`` is
        the first non-default version reported by a result (else ``"1"``). When
        the plugin has no ``normalizer()``, every record is dropped with reason
        ``"<record_id>:no_normalizer"``.
        """
        normalizer = self._normalizer()
        if normalizer is None:
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{record.provider_record_id}:no_normalizer" for record in records],
                normalizer_version="1",
            )

        events: list = []
        skipped = 0
        dropped: list[str] = []
        aggregate_version = "1"
        for record in records:
            result = normalizer.normalize(record)
            events.extend(result.events)
            skipped += result.skipped
            dropped.extend(result.dropped)
            # First non-default version wins; stays "1" when every result
            # reports the default.
            if aggregate_version == "1" and result.normalizer_version and result.normalizer_version != "1":
                aggregate_version = result.normalizer_version
        return NormalizationResult(
            events=events,
            skipped=skipped,
            dropped=dropped,
            normalizer_version=aggregate_version,
        )


__all__ = ["NormalizationEngine"]
