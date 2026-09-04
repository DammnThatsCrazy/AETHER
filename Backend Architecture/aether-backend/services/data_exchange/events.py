"""Data Exchange Plane typed-event catalog (M0: declared, not yet emitted).

Events are emitted as telemetry/audit side effects through the canonical
``EventProducer`` (``shared/events/events.py``).  Topic names follow the
repository's dotted convention ``aether.<domain>.<event>``.

Milestone note (M0): these constants are inert.  The live ``Topic`` enum in
``shared/events/events.py`` and its TS twin ``packages/shared/events.ts`` /
``CANONICAL_EVENT_TYPES`` are only extended when the first emitter lands
(M3 imports, M4 exports, M5 reports).  Adding a topic before an emitter
exists would fail event-schema parity checks.
"""

from __future__ import annotations

from typing import Final

# ── artifact lifecycle ──────────────────────────────────────────────────────
DATA_ARTIFACT_CREATED: Final[str] = "aether.data_exchange.artifact.created"
DATA_ARTIFACT_AVAILABLE: Final[str] = "aether.data_exchange.artifact.available"
DATA_ARTIFACT_EXPIRED: Final[str] = "aether.data_exchange.artifact.expired"
DATA_ARTIFACT_DELETED: Final[str] = "aether.data_exchange.artifact.deleted"

# ── ingress (imports) ───────────────────────────────────────────────────────
IMPORT_CREATED: Final[str] = "aether.data_exchange.import.created"
IMPORT_UPLOADED: Final[str] = "aether.data_exchange.import.uploaded"
IMPORT_ANALYZED: Final[str] = "aether.data_exchange.import.analyzed"
IMPORT_VALIDATED: Final[str] = "aether.data_exchange.import.validated"
IMPORT_APPROVED: Final[str] = "aether.data_exchange.import.approved"
IMPORT_COMMIT_STARTED: Final[str] = "aether.data_exchange.import.commit_started"
IMPORT_COMMITTED: Final[str] = "aether.data_exchange.import.committed"
IMPORT_PARTIALLY_COMMITTED: Final[str] = "aether.data_exchange.import.partially_committed"
IMPORT_FAILED: Final[str] = "aether.data_exchange.import.failed"
IMPORT_ROLLED_BACK: Final[str] = "aether.data_exchange.import.rolled_back"
IMPORT_REPLAYED: Final[str] = "aether.data_exchange.import.replayed"

# ── egress (exports) ────────────────────────────────────────────────────────
EXPORT_REQUESTED: Final[str] = "aether.data_exchange.export.requested"
EXPORT_GENERATING: Final[str] = "aether.data_exchange.export.generating"
EXPORT_AVAILABLE: Final[str] = "aether.data_exchange.export.available"
EXPORT_FAILED: Final[str] = "aether.data_exchange.export.failed"
EXPORT_DOWNLOADED: Final[str] = "aether.data_exchange.export.downloaded"

# ── reports ─────────────────────────────────────────────────────────────────
REPORT_REQUESTED: Final[str] = "aether.data_exchange.report.requested"
REPORT_AVAILABLE: Final[str] = "aether.data_exchange.report.available"
REPORT_FAILED: Final[str] = "aether.data_exchange.report.failed"


# Every declared topic, in one place, so the M3 registration sweep is a diff of
# this tuple onto the live Topic enum + CANONICAL_EVENT_TYPES.
DATA_EXCHANGE_TOPICS: Final[tuple[str, ...]] = (
    DATA_ARTIFACT_CREATED,
    DATA_ARTIFACT_AVAILABLE,
    DATA_ARTIFACT_EXPIRED,
    DATA_ARTIFACT_DELETED,
    IMPORT_CREATED,
    IMPORT_UPLOADED,
    IMPORT_ANALYZED,
    IMPORT_VALIDATED,
    IMPORT_APPROVED,
    IMPORT_COMMIT_STARTED,
    IMPORT_COMMITTED,
    IMPORT_PARTIALLY_COMMITTED,
    IMPORT_FAILED,
    IMPORT_ROLLED_BACK,
    IMPORT_REPLAYED,
    EXPORT_REQUESTED,
    EXPORT_GENERATING,
    EXPORT_AVAILABLE,
    EXPORT_FAILED,
    EXPORT_DOWNLOADED,
    REPORT_REQUESTED,
    REPORT_AVAILABLE,
    REPORT_FAILED,
)
