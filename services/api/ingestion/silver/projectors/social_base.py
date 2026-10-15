"""Base class for the six Social Silver projectors (M3 Social Silver plane).

Each SocialSilver fact kind (identity / connection / interaction / content /
community membership / metric) has its own projector because the Silver
projection plane is one-projector-per-table (the ownership registry maps each
registered projector to exactly one ``silver_*_facts`` table). They share this
base so the provenance/record handling stays in one place.

Conventions inherited from the Silver plane (BaseProjector):

- idempotency: rows carry ``source_event_id`` + a deterministic per-fact
  ``idempotency_key``; the writer dedupes with ``ON CONFLICT DO NOTHING``.
- ownership: every row starts from ``_base_row`` (tenant_id / source_event_id /
  source_event_type / idempotency_key / consent_snapshot_id / privacy_class /
  occurred_at / actor_id / user_id / ...), then domain columns are added.
- consent: recorded (not enforced) at insert — see social_common docstring.
- canonical provenance: ``source_scope`` + ``evidence_basis`` are resolved from
  the provider envelope (explicit stamp, else acquisition-mode derivation,
  else null / ``unknown``) — never guessed. See social_common.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProjector, ProjectionResult
from .social_common import (
    compose_idempotency_key,
    provider_identity_of,
    provider_platform_of,
    records_of,
    resolve_evidence_basis,
    resolve_source_scope,
)


class SocialFactProjector(BaseProjector):
    """Base for a single-table Social Silver projector.

    Subclasses set ``handles`` and ``table`` and implement ``build_row``.
    """

    #: silver_<domain>_facts table this projector writes.
    table: str = ""

    #: canonical fact kind (one of the six SocialSilver consts) for doc/audit.
    fact_kind: str = ""

    #: natural discriminator used to build per-record idempotency keys.
    #: Subclasses may override ``_record_key`` instead.
    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        props = self._props(event)
        rows: list[dict[str, Any]] = []
        for record in records_of(props):
            row = self.build_row(event, record)
            if row:
                rows.append(row)
        if not rows:
            return ProjectionResult(
                table=self.table,
                rows=[],
                skipped=True,
                skip_reason="no_projectable_social_record",
            )
        return ProjectionResult(table=self.table, rows=rows)

    # -- subclass contract --------------------------------------------------

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Return one silver row for a provider record, or None to skip it."""
        raise NotImplementedError

    # -- shared row plumbing -------------------------------------------------

    def _base_social_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        """Base row (BaseProjector ownership) + canonical provenance columns."""
        row = self._base_row(event)
        source_event_id = row.get("source_event_id")
        # canonical provider (platform) identity, e.g. "x" / "twitter".
        provider_identity = provider_platform_of(event, record) or (
            str(record.get("provider_identity") or "") or None
        ) or provider_identity_of(event, record)
        provider_record_ref = (
            str(record.get("provider_record_id") or record.get("record_id") or "")
            or None
        )
        row.update({
            # canonical provenance — resolved, never guessed (see social_common).
            "source_scope": resolve_source_scope(event, record),
            "evidence_basis": resolve_evidence_basis(event, record),
            # data-rights authorization the fact was collected under.
            "rights_ref": (
                str(record.get("rights_ref") or record.get("consent_ref") or "")
                or row.get("consent_snapshot_id")
            ),
            "provider_identity": provider_identity,
            "provider_record_ref": provider_record_ref,
        })
        # A per-record idempotency key keeps multi-record fan-out replay-safe.
        # When a single provider record is the whole event the key equals the
        # source_event_id (matching single-row projector convention); otherwise
        # it is <source_event_id>:<natural discriminator>.
        key_part = self._record_key(event, record)
        if key_part:
            row["idempotency_key"] = compose_idempotency_key(source_event_id, key_part)
        return row

    def _record_key(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> str | None:
        """Stable per-record discriminator for the idempotency key.

        Default: the provider record id (stable across replays). A subclass may
        override to use its natural key. Returns None for a single-record event
        so the key reduces to the bare source_event_id.
        """
        if self._is_single_record(event):
            return None
        ref = (
            str(record.get("provider_record_id") or record.get("record_id") or "")
        ).strip()
        return ref or str(record.get("provider_content_id") or "") or None

    def _is_single_record(self, event: dict[str, Any]) -> bool:
        props = self._props(event)
        batch = props.get("records")
        return not isinstance(batch, list)

    @staticmethod
    def _provider_family(event: dict[str, Any], record: dict[str, Any]) -> str | None:
        """Platform identity for a fact (canonical ``provider_identity``)."""
        return provider_platform_of(event, record)
