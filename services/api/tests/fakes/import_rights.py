"""Rights fixtures for import-commit tests.

Committing an import requires a named approver and a rights grant for the import's
source, so tests that drive an import all the way to commit grant their own source.
"""
from __future__ import annotations

import uuid


async def grant_import_source(tenant_id: str, actor: str = "approver-1") -> str:
    """Create a tenant-owned source grant that admits graph and lake writes; return its ID."""
    from connectors.integrations.data_rights.models import DataRightsGrantCreate
    from connectors.integrations.data_rights.service import data_rights_service

    source_id = f"import-test-source:{uuid.uuid4().hex}"
    await data_rights_service.create_grant(
        DataRightsGrantCreate(
            tenant_id=tenant_id,
            source_id=source_id,
            connector_id="csv_import",
            connector_class="tenant_import",
            data_category="customer",
            data_sensitivity="sensitive_pii",
            raw_data_owner="tenant",
            source_relationship="organization_system",
            tenant_lake_allowed=True,
            tenant_graph_allowed=True,
            tenant_insights_allowed=True,
            legal_basis="contract",
        ),
        granted_by_user_id=actor,
    )
    return source_id
