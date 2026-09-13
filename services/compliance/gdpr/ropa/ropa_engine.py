"""
Aether GDPR — Record of Processing Activities (Article 30)
Maintains the mandatory register of all processing activities.
Tracks legal basis, data categories, recipients, cross-border transfers,
and retention periods for each activity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from config.compliance_config import CROSS_BORDER_TRANSFERS, PROCESSING_ACTIVITIES
from shared.logger import ropa_log


@dataclass
class ROPAEntry:
    """A single entry in the Record of Processing Activities."""
    name: str
    purpose: str
    legal_basis: str
    data_categories: list
    data_subjects: str
    recipients: list
    cross_border: bool
    retention: str
    safeguards: str
    last_reviewed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dpia_required: bool = False
    dpia_completed: bool = False
    status: str = "active"


# ═══════════════════════════════════════════════════════════════════════════
# ROPA ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class ROPAEngine:
    """Manages the Record of Processing Activities (Art. 30)."""

    def __init__(self):
        self._entries: list = []
        self._load_from_config()

    def _load_from_config(self):
        """Load processing activities from central config."""
        for activity in PROCESSING_ACTIVITIES:
            entry = ROPAEntry(
                name=activity.name,
                purpose=activity.purpose,
                legal_basis=activity.legal_basis,
                data_categories=list(activity.data_categories),
                data_subjects=activity.data_subjects,
                recipients=list(activity.recipients),
                cross_border=activity.cross_border,
                retention=activity.retention,
                safeguards=activity.safeguards,
            )
            # Activities involving profiling or special categories need DPIA
            if "profiling" in activity.purpose.lower() or "prediction" in activity.purpose.lower():
                entry.dpia_required = True
            self._entries.append(entry)

    def add_activity(self, name: str, purpose: str, legal_basis: str,
                     data_categories: list, data_subjects: str,
                     recipients: list, retention: str,
                     cross_border: bool = False, safeguards: str = "") -> ROPAEntry:
        """Register a new processing activity."""
        entry = ROPAEntry(
            name=name, purpose=purpose, legal_basis=legal_basis,
            data_categories=data_categories, data_subjects=data_subjects,
            recipients=recipients, cross_border=cross_border,
            retention=retention, safeguards=safeguards,
        )
        self._entries.append(entry)
        ropa_log(f"New activity registered: {name}")
        return entry

    def list_activities(self, cross_border_only: bool = False) -> list:
        """List all registered processing activities."""
        entries = self._entries
        if cross_border_only:
            entries = [e for e in entries if e.cross_border]
        return entries

    def dpia_required_activities(self) -> list:
        """List activities requiring a Data Protection Impact Assessment."""
        return [e for e in self._entries if e.dpia_required and not e.dpia_completed]

    def cross_border_report(self) -> list:
        """Generate cross-border transfer report (Chapter V)."""
        report = []
        for transfer in CROSS_BORDER_TRANSFERS:
            report.append({
                "destination": transfer.destination,
                "sub_processor": transfer.sub_processor,
                "mechanism": transfer.transfer_mechanism,
                "data_categories": transfer.data_categories,
                "tia_completed": transfer.tia_completed,
            })
        return report

    def print_register(self):
        """Print the full ROPA register."""
        ropa_log(f"\nRecord of Processing Activities — {len(self._entries)} entries\n")

        for i, entry in enumerate(self._entries, 1):
            ropa_log(f"  {i}. {entry.name}")
            ropa_log(f"     Purpose: {entry.purpose}")
            ropa_log(f"     Legal Basis: {entry.legal_basis}")
            ropa_log(f"     Data Categories: {', '.join(entry.data_categories)}")
            ropa_log(f"     Data Subjects: {entry.data_subjects}")
            ropa_log(f"     Recipients: {', '.join(entry.recipients)}")
            ropa_log(f"     Cross-Border: {'Yes' if entry.cross_border else 'No'}")
            ropa_log(f"     Retention: {entry.retention}")
            ropa_log(f"     Safeguards: {entry.safeguards}")
            if entry.dpia_required:
                status = "Completed" if entry.dpia_completed else "REQUIRED"
                ropa_log(f"     DPIA: {status}")
            ropa_log("")

    def print_transfer_report(self):
        """Print cross-border transfer report."""
        transfers = self.cross_border_report()
        ropa_log(f"\nCross-Border Transfers — {len(transfers)} transfers\n")
        for t in transfers:
            tia = "Completed" if t["tia_completed"] else "PENDING"
            ropa_log(f"  → {t['destination']} ({t['sub_processor']})")
            ropa_log(f"    Mechanism: {t['mechanism']}")
            ropa_log(f"    Data: {', '.join(t['data_categories'])}")
            ropa_log(f"    TIA: {tia}")
            ropa_log("")

    @property
    def summary(self) -> dict:
        cross_border = sum(1 for e in self._entries if e.cross_border)
        dpia_pending = len(self.dpia_required_activities())
        return {
            "total_activities": len(self._entries),
            "cross_border": cross_border,
            "dpia_required": sum(1 for e in self._entries if e.dpia_required),
            "dpia_pending": dpia_pending,
            "transfers": len(CROSS_BORDER_TRANSFERS),
        }
