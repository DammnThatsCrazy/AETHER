"""Data Exchange Plane typed-event catalog.

Events are emitted as telemetry/audit side effects through the canonical
``EventProducer`` (``shared/events/events.py``).  Topic names follow the
repository's dotted convention ``aether.<domain>.<event>``.

Which entries are actually live: the ``Topic`` enum in
``shared/events/events.py`` is extended only when a first emitter lands, and
only for *genuinely net-new* envelope vocabulary.  Today that is
``DATA_EXCHANGE_ARTIFACT_UPLOADED`` (transfer uploads) and the four
``REPORT_*`` members.  The ``DATA_ARTIFACT_*`` / ``IMPORT_*`` / ``EXPORT_*``
entries below document envelope *intents* that deliberately reuse the
canonical ``IMPORT_*`` / ``EXPORT_*`` ``Topic`` members — they are not
separately registered (no duplicate import/export vocabulary).
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

# ── reports (live: registered on the Topic enum at M5) ──────────────────────
# Values mirror the live ``Topic`` members (``aether.report.*``): the reports
# plane follows the top-level-domain naming of the canonical import/export
# families (``aether.import.*`` / ``aether.export.*``) rather than nesting
# under ``aether.data_exchange``.  ``REPORT_DOWNLOADED`` mirrors the canonical
# export-download audit topic.
REPORT_REQUESTED: Final[str] = "aether.report.requested"
REPORT_AVAILABLE: Final[str] = "aether.report.available"
REPORT_FAILED: Final[str] = "aether.report.failed"
REPORT_DOWNLOADED: Final[str] = "aether.report.downloaded"


# Every declared topic, in one place.  Only the genuinely-net-new members
# (``DATA_EXCHANGE_ARTIFACT_UPLOADED``, ``REPORT_*``) exist on the live
# ``Topic`` enum; the ``DATA_ARTIFACT_*`` / ``IMPORT_*`` / ``EXPORT_*`` intents
# reuse the canonical members and must NOT be registered separately.
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
    REPORT_DOWNLOADED,
)
