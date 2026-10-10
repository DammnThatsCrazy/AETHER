"""Identity resolution metrics emission.

All metrics are emitted through the shared metrics client so they appear
in Prometheus / the Kyber operator console.
"""

from __future__ import annotations

from shared.logger.logger import metrics as _metrics


class IdentityMetrics:
    """Thin wrapper around the shared metrics client for identity signals."""

    def record_resolve(self, success: bool, tenant_id: str = "") -> None:
        labels = {"tenant_id": tenant_id} if tenant_id else {}
        _metrics.increment("identity_resolve_total", labels=labels)
        if success:
            _metrics.increment("identity_resolve_success_total", labels=labels)
        else:
            _metrics.increment("identity_resolve_error_total", labels=labels)

    def record_merge(self, tenant_id: str = "") -> None:
        labels = {"tenant_id": tenant_id} if tenant_id else {}
        _metrics.increment("identity_merge_total", labels=labels)

    def record_link(self, tenant_id: str = "") -> None:
        _metrics.increment("identity_link_total")

    def record_candidate(self) -> None:
        _metrics.increment("identity_candidate_total")

    def record_conflict(self) -> None:
        _metrics.increment("identity_conflict_total")

    def record_split(self, tenant_id: str = "") -> None:
        labels = {"tenant_id": tenant_id} if tenant_id else {}
        _metrics.increment("identity_split_total", labels=labels)

    def record_blocked(self, reason: str) -> None:
        _metrics.increment("identity_blocked_total")
        if reason == "consent":
            _metrics.increment("identity_blocked_consent_total")
        elif reason == "cross_tenant":
            _metrics.increment("identity_blocked_cross_tenant_total")
        elif reason == "fingerprint_only":
            _metrics.increment("identity_blocked_fingerprint_only_total")

    def record_duplicate_alias(self) -> None:
        _metrics.increment("identity_duplicate_alias_total")

    def record_graph_edge_writes(self, count: int) -> None:
        if count > 0:
            _metrics.increment("identity_graph_edge_write_total", value=count)

    def record_graph_edge_error(self) -> None:
        _metrics.increment("identity_graph_edge_write_error_total")

    def record_signal_observation(self, signal_type: str) -> None:
        _metrics.increment(
            "identity_signal_type_distribution",
            labels={"signal_type": signal_type},
        )

    # ── Identity assurance / verification metrics ──────────────────────────

    def record_verification_challenge(self, method: str) -> None:
        _metrics.increment(
            "identity_verification_challenge_total", labels={"method": method}
        )

    def record_verification_success(self, method: str) -> None:
        _metrics.increment(
            "identity_verification_success_total", labels={"method": method}
        )

    def record_verification_failure(self, reason: str) -> None:
        _metrics.increment(
            "identity_verification_failure_total", labels={"reason": reason}
        )

    def record_verification_expired(self) -> None:
        _metrics.increment("identity_verification_expired_total")

    def record_evidence_active(self, evidence_type: str) -> None:
        _metrics.increment(
            "identity_verification_evidence_active_total",
            labels={"evidence_type": evidence_type},
        )

    def record_evidence_revoked(self, evidence_type: str) -> None:
        _metrics.increment(
            "identity_verification_evidence_revoked_total",
            labels={"evidence_type": evidence_type},
        )

    def record_resolution_replay(self, result: str) -> None:
        _metrics.increment(
            "identity_resolution_replay_total", labels={"result": result}
        )
