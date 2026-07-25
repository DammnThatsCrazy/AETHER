from __future__ import annotations

from repositories.repos import (
    AdminRepository,
    AlertRepository,
    BaseRepository,
    CampaignRepository,
    EconomicResourceRepository,
    EntityRepository,
    PaymentIntentRepository,
    ProvidersRepository,
    SettlementEventRepository,
    UserRepository,
    InvestigationRepository,
)
from repositories.commerce_repos import (
    ApprovalsRepository,
    EntitlementsRepository,
    FacilitatorsRepository,
    PoliciesRepository,
    ResourcesRepository,
    SettlementsRepository,
)
from repositories.imports_repo import ImportsRepository
from services.data_quality.repositories import IntelligenceQualityRepository
from services.metering_evidence.service import MeteringEvidenceRepository


def domain_repositories() -> dict[str, BaseRepository]:
    """Canonical repositories used by the normal API read paths."""
    imports = ImportsRepository()
    return {
        "tenants": AdminRepository(),
        "users": UserRepository(),
        "entities": EntityRepository(),
        "campaigns": CampaignRepository(),
        "economic_resources": EconomicResourceRepository(),
        "payment_intents": PaymentIntentRepository(),
        "settlement_events": SettlementEventRepository(),
        "alerts": AlertRepository(),
        "providers": ProvidersRepository(),
        "metering_evidence": MeteringEvidenceRepository(),
        "data_quality_scores": IntelligenceQualityRepository(),
        "import_sessions": imports.sessions,
        "investigations": InvestigationRepository(),
        "commerce_resources": ResourcesRepository(),
        "commerce_policies": PoliciesRepository(),
        "commerce_facilitators": FacilitatorsRepository(),
        "commerce_approvals": ApprovalsRepository(),
        "commerce_settlements": SettlementsRepository(),
        "commerce_entitlements": EntitlementsRepository(),
    }


class SeedRunRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("demo_seed_runs")


class SeedOwnershipRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("demo_seed_record_ownership")


class SeedResetAuditRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("demo_seed_reset_audit")
