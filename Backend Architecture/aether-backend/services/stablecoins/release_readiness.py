"""Stablecoin Intelligence release readiness matrix for PR4 gates."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StablecoinReleaseCapability:
    name: str
    status: str
    description: str
    completed_items: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.status == "complete" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "complete": self.complete,
            "description": self.description,
            "completed_items": list(self.completed_items),
            "blockers": list(self.blockers),
        }


class StablecoinReleaseReadinessService:
    def capabilities(self) -> list[StablecoinReleaseCapability]:
        return [
            StablecoinReleaseCapability(
                "kyber_operations",
                "partial",
                "Operator health, lineage, and audited remediation-intent capture.",
                ["tenant health summary", "observation lineage composer", "durable remediation audit records"],
                ["operator UI not implemented", "remediation workers not implemented"],
            ),
            StablecoinReleaseCapability(
                "olympus_market_intelligence",
                "partial",
                "Governed benchmark publication with cohort and data-class controls.",
                ["tenant_raw benchmark blocking", "minimum cohort enforcement", "estimate labeling"],
                ["market trend UI not implemented", "licensed provider validation not implemented"],
            ),
            StablecoinReleaseCapability(
                "commercial_controls",
                "partial",
                "Capability checks and stablecoin usage metering.",
                ["capability enum", "capability decision helper", "metering summary"],
                ["billing-plan mapping not wired", "quota enforcement not wired"],
            ),
            StablecoinReleaseCapability(
                "security_release_evidence",
                "partial",
                "Release evidence reports and explicit non-GA recommendation.",
                ["PR4 release-readiness report", "tenant-isolation evidence scaffold", "security evidence scaffold"],
                ["staging validation not run", "backup/restore not run", "load/chaos tests not run"],
            ),
        ]

    def readiness(self) -> dict[str, Any]:
        caps = self.capabilities()
        blockers = [b for cap in caps for b in cap.blockers]
        return {
            "release_gate": "controlled_staging_only",
            "production_recommendation": "NOT_READY",
            "ga_ready": False,
            "capabilities_total": len(caps),
            "capabilities_complete": sum(1 for cap in caps if cap.complete),
            "capabilities_partial": sum(1 for cap in caps if cap.status == "partial"),
            "blocker_count": len(blockers),
            "capabilities": [cap.as_dict() for cap in caps],
        }
