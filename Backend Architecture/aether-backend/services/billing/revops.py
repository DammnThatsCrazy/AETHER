"""Billing-ready revenue operations contracts, repositories, and services."""
from __future__ import annotations

import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from repositories.repos import BaseRepository
from shared.common.common import BadRequestError, NotFoundError, utc_now

ContractStatus = Literal['draft','active','pending_signature','expired','cancelled','renewal_pending']
BillingModel = Literal['flat_subscription','usage_based','hybrid','enterprise_contract','value_based','pilot']
BillingPeriod = Literal['monthly','quarterly','annual','custom']
ResetPeriod = Literal['monthly','quarterly','annual','never']
MeteringEventType = Literal['event_ingested','entity_resolved','graph_operation','profile_query','recommendation_generated','recommendation_previewed','decision_recorded','confidence_updated','action_logged','action_dispatched','outcome_observed','playbook_run','investigation_opened','audit_export_generated','integration_delivery','connector_sync','webhook_ingested','sdk_event_ingested','premium_connector_used','deployment_mode_active','managed_workflow_triggered','value_created']
InvoiceStatus = Literal['draft','review_ready','approved','exported']
ValueSourceType = Literal['outcome','playbook','recommendation_family','integration_action','manual_adjustment']
ValueType = Literal['retained_revenue','expansion_revenue','avoided_loss','campaign_waste_reduced','operational_savings','agent_failure_cost_reduced','manual_review_savings']
LeakageType = Literal['overage_not_priced','premium_module_unpriced','connector_unpriced','value_created_unmonetized','deployment_underpriced','services_unbilled','audit_exports_unpriced']
Severity = Literal['low','medium','high','critical']

SECRET_RE = re.compile(r"(api[_-]?key|secret|token|password|authorization|credential|private[_-]?key)", re.I)
DIMENSION_LABELS = {
    'event_ingested': 'Events ingested', 'entity_resolved': 'Entities resolved', 'graph_operation': 'Graph operations',
    'profile_query': 'Profile360 queries', 'recommendation_generated': 'Recommendations generated', 'decision_recorded': 'Decisions recorded',
    'action_logged': 'Actions logged', 'action_dispatched': 'Actions dispatched', 'outcome_observed': 'Outcomes observed',
    'playbook_run': 'Playbook runs', 'audit_export_generated': 'Audit exports generated', 'integration_delivery': 'Integration deliveries',
    'recommendation_previewed': 'Recommendations previewed', 'confidence_updated': 'Confidence updates',
    'investigation_opened': 'Investigations opened', 'connector_sync': 'Connector syncs',
    'webhook_ingested': 'Webhook events ingested', 'sdk_event_ingested': 'SDK events ingested',
    'premium_connector_used': 'Premium connector usage', 'deployment_mode_active': 'Deployment mode activations',
    'managed_workflow_triggered': 'Managed workflow triggers', 'value_created': 'Value-created events',
}
PREMIUM_DIMENSIONS = {'premium_connector_used','deployment_mode_active','managed_workflow_triggered'}


def now_iso() -> str:
    return utc_now().isoformat()


def parse_dt(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def in_period(record: dict[str, Any], start: str, end: str, field: str = 'occurred_at') -> bool:
    ts = parse_dt(record.get(field))
    s = parse_dt(start)
    e = parse_dt(end)
    if ts is None or s is None or e is None:
        return True
    return s <= ts < e


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if SECRET_RE.search(str(key)):
            continue
        if isinstance(value, str) and SECRET_RE.search(value[:80]):
            cleaned[key] = '[redacted]'
        elif isinstance(value, dict):
            cleaned[key] = sanitize_metadata(value)
        else:
            cleaned[key] = value
    return cleaned


class TenantContractProfile(BaseModel):
    contract_profile_id: str = Field(default_factory=lambda: f"contract_{uuid.uuid4().hex}")
    tenant_id: str
    account_id: str | None = None
    package_id: str | None = None
    plan_tier: str | None = None
    contract_status: ContractStatus = 'draft'
    billing_model: BillingModel = 'pilot'
    contract_start_date: str | None = None
    contract_end_date: str | None = None
    renewal_date: str | None = None
    billing_period: BillingPeriod = 'monthly'
    currency: str = 'USD'
    payment_terms: str | None = None
    internal_notes: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TenantEntitlement(BaseModel):
    entitlement_id: str = Field(default_factory=lambda: f"entitlement_{uuid.uuid4().hex}")
    tenant_id: str
    package_id: str | None = None
    feature_key: str
    enabled: bool = True
    included_quantity: float | None = None
    overage_allowed: bool = False
    overage_unit_price_notes: str | None = None
    reset_period: ResetPeriod = 'monthly'
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class UsageMeteringEvent(BaseModel):
    metering_event_id: str = Field(default_factory=lambda: f"meter_{uuid.uuid4().hex}")
    tenant_id: str
    event_type: MeteringEventType
    quantity: float = Field(default=1, ge=0)
    source_id: str | None = None
    source_type: str | None = None
    billable: bool = True
    package_id: str | None = None
    occurred_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] | None = None


class BillableUsageSummary(BaseModel):
    tenant_id: str
    billing_period_start: str
    billing_period_end: str
    package_id: str | None = None
    usage_by_dimension: dict[str, float]
    included_usage_by_dimension: dict[str, float]
    overage_by_dimension: dict[str, float]
    billable_events_count: int
    non_billable_events_count: int
    estimated_charges_notes: str | None = None
    generated_at: str = Field(default_factory=now_iso)


class InvoicePreviewLineItem(BaseModel):
    line_item_id: str = Field(default_factory=lambda: f"line_{uuid.uuid4().hex}")
    label: str
    dimension_key: str
    quantity: float
    included_quantity: float | None = None
    overage_quantity: float | None = None
    unit_price_notes: str | None = None
    amount_notes: str | None = None
    source_event_ids: list[str] | None = None


class InvoicePreview(BaseModel):
    invoice_preview_id: str = Field(default_factory=lambda: f"invoice_preview_{uuid.uuid4().hex}")
    tenant_id: str
    contract_profile_id: str | None = None
    billing_period_start: str
    billing_period_end: str
    line_items: list[InvoicePreviewLineItem]
    subtotal_notes: str | None = None
    value_created_summary: dict[str, Any] | None = None
    status: InvoiceStatus = 'draft'
    generated_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ValueCreatedEvent(BaseModel):
    value_event_id: str = Field(default_factory=lambda: f"value_{uuid.uuid4().hex}")
    tenant_id: str
    source_type: ValueSourceType
    source_id: str
    value_type: ValueType
    value_amount: float | None = None
    currency: str | None = None
    confidence: float | None = None
    attribution_notes: str | None = None
    billable_under_contract: bool = False
    occurred_at: str = Field(default_factory=now_iso)


class RevenueLeakageSignal(BaseModel):
    signal_id: str = Field(default_factory=lambda: f"leak_{uuid.uuid4().hex}")
    tenant_id: str
    leakage_type: LeakageType
    reason: str
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = 'medium'
    recommended_action: str
    created_at: str = Field(default_factory=now_iso)
    resolved_at: str | None = None


class TenantContractProfileRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('tenant_contract_profiles')
    async def get_for_tenant(self, tenant_id: str) -> dict | None:
        rows = await self.find_many(filters={'tenant_id': tenant_id}, limit=1, sort_by='updated_at')
        return rows[0] if rows else None

class TenantEntitlementRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('tenant_entitlements')
    async def list_for_tenant(self, tenant_id: str, limit: int = 1000) -> list[dict]: return await self.find_many(filters={'tenant_id': tenant_id}, limit=limit)

class UsageMeteringEventRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('usage_metering_events')
    async def list_for_tenant_period(self, tenant_id: str, start: str, end: str, limit: int = 10000) -> list[dict]:
        return [r for r in await self.find_many(filters={'tenant_id': tenant_id}, limit=limit) if in_period(r, start, end)]
    async def find_idempotent(self, tenant_id: str, source_type: str, source_id: str, event_type: str) -> dict | None:
        rows = await self.find_many(filters={'tenant_id': tenant_id, 'source_type': source_type, 'source_id': source_id, 'event_type': event_type}, limit=1)
        return rows[0] if rows else None

class BillableUsageSummaryRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('billable_usage_summaries')
class InvoicePreviewRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('invoice_previews')
class ValueCreatedEventRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('value_created_events')
    async def list_for_tenant_period(self, tenant_id: str, start: str, end: str, limit: int = 10000) -> list[dict]:
        return [r for r in await self.find_many(filters={'tenant_id': tenant_id}, limit=limit) if in_period(r, start, end)]
class RevenueLeakageSignalRepository(BaseRepository):
    def __init__(self) -> None: super().__init__('revenue_leakage_signals')


class MeteringService:
    def __init__(self, events: UsageMeteringEventRepository | None = None) -> None:
        self.events = events or UsageMeteringEventRepository()
    def enabled(self) -> bool:
        return os.getenv('AETHER_USAGE_METERING_ENABLED', 'true').lower() not in {'0','false','no'}
    async def record_event(self, event: UsageMeteringEvent) -> dict | None:
        if not self.enabled():
            return None
        data = event.model_dump()
        data['metadata'] = sanitize_metadata(data.get('metadata'))
        if event.source_id and event.source_type:
            existing = await self.events.find_idempotent(event.tenant_id, event.source_type, event.source_id, event.event_type)
            if existing:
                return existing
        return await self.events.insert(event.metering_event_id, data)


class EntitlementService:
    def __init__(self, contracts: TenantContractProfileRepository | None = None, entitlements: TenantEntitlementRepository | None = None) -> None:
        self.contracts = contracts or TenantContractProfileRepository()
        self.entitlements = entitlements or TenantEntitlementRepository()
    async def profile(self, tenant_id: str) -> dict | None: return await self.contracts.get_for_tenant(tenant_id)
    async def evaluate(self, tenant_id: str, usage: dict[str, float] | None = None, package_id: str | None = None) -> dict[str, Any]:
        contract = await self.profile(tenant_id)
        ents = await self.entitlements.list_for_tenant(tenant_id)
        by_feature = {e['feature_key']: e for e in ents}
        usage = usage or {}
        included = {k: float(v.get('included_quantity') or 0) for k, v in by_feature.items()}
        overages: dict[str, float] = {}
        disabled: list[str] = []
        unpriced: list[str] = []
        for dim, qty in usage.items():
            ent = by_feature.get(dim)
            if ent is None or not ent.get('enabled', True):
                disabled.append(dim)
            inc = float(ent.get('included_quantity') or 0) if ent else 0
            over = max(float(qty) - inc, 0)
            if over:
                overages[dim] = over
                if not ent or (ent.get('overage_allowed') and not ent.get('overage_unit_price_notes')):
                    unpriced.append(dim)
        package_mismatch = bool(contract and package_id and contract.get('package_id') and package_id != contract.get('package_id'))
        return {'contract_profile': contract, 'entitlements': ents, 'enabled_features': [k for k,e in by_feature.items() if e.get('enabled', True)], 'included_usage': included, 'overages': overages, 'disabled_feature_usage': disabled, 'package_mismatch': package_mismatch, 'unpriced_overages': unpriced}


class UsageSummaryService:
    def __init__(self, events: UsageMeteringEventRepository | None = None, entitlements: EntitlementService | None = None, summaries: BillableUsageSummaryRepository | None = None) -> None:
        self.events = events or UsageMeteringEventRepository()
        self.entitlements = entitlements or EntitlementService()
        self.summaries = summaries or BillableUsageSummaryRepository()
    async def calculate(self, tenant_id: str, start: str, end: str, package_id: str | None = None, persist: bool = False) -> dict:
        records = await self.events.list_for_tenant_period(tenant_id, start, end)
        if package_id: records = [r for r in records if r.get('package_id') in (None, package_id)]
        usage = Counter()
        source_ids = defaultdict(list)
        billable = 0
        non_billable = 0
        for r in records:
            dim = r.get('event_type')
            qty = float(r.get('quantity') or 0)
            usage[dim] += qty
            source_ids[dim].append(r.get('metering_event_id') or r.get('id'))
            if r.get('billable'): billable += 1
            else: non_billable += 1
        evaluation = await self.entitlements.evaluate(tenant_id, dict(usage), package_id)
        summary = BillableUsageSummary(tenant_id=tenant_id,billing_period_start=start,billing_period_end=end,package_id=package_id,usage_by_dimension=dict(usage),included_usage_by_dimension=evaluation['included_usage'],overage_by_dimension=evaluation['overages'],billable_events_count=billable,non_billable_events_count=non_billable,estimated_charges_notes='Amounts remain notes until pricing configuration is attached.').model_dump()
        summary['source_event_ids_by_dimension'] = dict(source_ids)
        if persist:
            rid = f"summary_{tenant_id}_{start}_{end}_{package_id or 'all'}".replace(':','_')
            await self.summaries.insert(rid, summary)
        return summary


class InvoicePreviewService:
    def __init__(self) -> None:
        self.contracts = TenantContractProfileRepository()
        self.entitlements = EntitlementService()
        self.summary = UsageSummaryService(entitlements=self.entitlements)
        self.previews = InvoicePreviewRepository()
        self.values = ValueCreatedEventRepository()
    async def generate(self, tenant_id: str, start: str, end: str) -> dict:
        contract = await self.contracts.get_for_tenant(tenant_id)
        usage = await self.summary.calculate(tenant_id, start, end, contract.get('package_id') if contract else None)
        ents = {e['feature_key']: e for e in await self.entitlements.entitlements.list_for_tenant(tenant_id)}
        line_items = []
        for dim, qty in usage['usage_by_dimension'].items():
            ent = ents.get(dim, {})
            line_items.append(InvoicePreviewLineItem(label=DIMENSION_LABELS.get(dim, dim.replace('_',' ').title()), dimension_key=dim, quantity=qty, included_quantity=ent.get('included_quantity'), overage_quantity=usage['overage_by_dimension'].get(dim, 0), unit_price_notes=ent.get('overage_unit_price_notes') or 'No exact price configured; review contract notes.', amount_notes='Pending pricing configuration / contract review.', source_event_ids=usage.get('source_event_ids_by_dimension', {}).get(dim, [])).model_dump())
        values = await self.values.list_for_tenant_period(tenant_id, start, end)
        value_summary = {'event_count': len(values), 'known_value_total': round(sum(float(v.get('value_amount') or 0) for v in values), 2), 'currency': (contract or {}).get('currency', 'USD')}
        preview = InvoicePreview(tenant_id=tenant_id, contract_profile_id=(contract or {}).get('contract_profile_id'), billing_period_start=start, billing_period_end=end, line_items=line_items, subtotal_notes='Draft preview only; no external invoice or payment collection generated.', value_created_summary=value_summary).model_dump()
        return await self.previews.insert(preview['invoice_preview_id'], preview)
    async def update_status(self, invoice_preview_id: str, status: InvoiceStatus) -> dict:
        return await self.previews.update(invoice_preview_id, {'status': status, 'updated_at': now_iso()})


class ValueCreatedEventService:
    def __init__(self) -> None:
        self.values = ValueCreatedEventRepository()
        self.contracts = TenantContractProfileRepository()
        self.metering = MeteringService()
    async def create(self, event: ValueCreatedEvent) -> dict:
        contract = await self.contracts.get_for_tenant(event.tenant_id)
        data = event.model_dump()
        if contract and contract.get('billing_model') == 'value_based':
            data['billable_under_contract'] = True
        saved = await self.values.insert(data['value_event_id'], data)
        await self.metering.record_event(UsageMeteringEvent(tenant_id=event.tenant_id,event_type='value_created',quantity=1,source_type=event.source_type,source_id=event.source_id,billable=data['billable_under_contract'],metadata={'value_type': event.value_type, 'has_amount': event.value_amount is not None}))
        return saved
    async def generate_from_record(self, tenant_id: str, source_type: ValueSourceType, source_id: str, value_type: ValueType = 'operational_savings', value_amount: float | None = None, confidence: float | None = None, attribution_notes: str | None = None) -> dict:
        return await self.create(ValueCreatedEvent(tenant_id=tenant_id, source_type=source_type, source_id=source_id, value_type=value_type, value_amount=value_amount, confidence=confidence, attribution_notes=attribution_notes))


class RevenueLeakageService:
    def __init__(self) -> None:
        self.entitlements = EntitlementService()
        self.summary = UsageSummaryService(entitlements=self.entitlements)
        self.signals = RevenueLeakageSignalRepository()
        self.values = ValueCreatedEventRepository()
    async def detect(self, tenant_id: str, start: str, end: str) -> list[dict]:
        usage = await self.summary.calculate(tenant_id, start, end)
        evaluation = await self.entitlements.evaluate(tenant_id, usage['usage_by_dimension'])
        contract = evaluation['contract_profile'] or {}
        existing_keys = set()
        signals: list[dict] = []
        async def add(leakage_type: LeakageType, reason: str, metrics: dict[str, Any], severity: Severity, action: str):
            key = f"{tenant_id}:{leakage_type}:{reason}:{start}:{end}"
            if key in existing_keys: return
            existing_keys.add(key)
            sig = RevenueLeakageSignal(signal_id=f"leak_{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}", tenant_id=tenant_id, leakage_type=leakage_type, reason=reason, supporting_metrics=metrics, severity=severity, recommended_action=action).model_dump()
            signals.append(await self.signals.insert(sig['signal_id'], sig))
        for dim in evaluation['unpriced_overages']:
            await add('overage_not_priced', f'{dim} exceeded included usage without a priced overage note.', {'overage': evaluation['overages'].get(dim)}, 'high', 'Attach overage pricing notes or adjust entitlement.')
        for dim in evaluation['disabled_feature_usage']:
            if dim in PREMIUM_DIMENSIONS:
                await add('premium_module_unpriced' if dim != 'premium_connector_used' else 'connector_unpriced', f'{dim} usage occurred without an enabled entitlement.', {'usage': usage['usage_by_dimension'].get(dim)}, 'high', 'Review package support and add entitlement or block usage.')
        values = await self.values.list_for_tenant_period(tenant_id, start, end)
        total_value = sum(float(v.get('value_amount') or 0) for v in values)
        if total_value >= 10000 and contract.get('billing_model') != 'value_based':
            await add('value_created_unmonetized', 'High value created under a non value-based contract.', {'known_value_total': total_value, 'event_count': len(values)}, 'medium', 'Review value-based pricing or expansion packaging.')
        if usage['usage_by_dimension'].get('deployment_mode_active', 0) and contract.get('billing_model') not in {'enterprise_contract','hybrid'}:
            await add('deployment_underpriced', 'Regulated or isolated deployment mode is active without enterprise deployment terms.', {'activations': usage['usage_by_dimension'].get('deployment_mode_active')}, 'critical', 'Move tenant to enterprise deployment pricing review.')
        if usage['usage_by_dimension'].get('managed_workflow_triggered', 0) and not any('services' in str(e.get('feature_key','')) for e in evaluation['entitlements']):
            await add('services_unbilled', 'Managed workflow usage detected without services entitlement.', {'triggers': usage['usage_by_dimension'].get('managed_workflow_triggered')}, 'high', 'Add managed services terms or disable workflow trigger.')
        if usage['usage_by_dimension'].get('audit_export_generated', 0) >= 10 and not (contract.get('package_id') and 'audit' in contract.get('package_id','')):
            await add('audit_exports_unpriced', 'High audit export volume without audit/enterprise package support.', {'exports': usage['usage_by_dimension'].get('audit_export_generated')}, 'medium', 'Offer audit/compliance packaging.')
        return signals


class ExpansionBillingService:
    def __init__(self) -> None:
        self.summary = UsageSummaryService()
        self.leakage = RevenueLeakageSignalRepository()
        self.values = ValueCreatedEventRepository()
    async def opportunities(self, tenant_id: str | None = None, start: str | None = None, end: str | None = None) -> list[dict]:
        filters = {'tenant_id': tenant_id} if tenant_id else None
        signals = await self.leakage.find_many(filters=filters, limit=1000)
        opportunities = []
        for s in signals:
            if s.get('resolved_at'): continue
            kind = {'overage_not_priced':'overage_threshold_crossed','premium_module_unpriced':'premium_module_fit_detected','connector_unpriced':'high_integration_volume_detected','deployment_underpriced':'enterprise_deployment_need_detected','services_unbilled':'managed_services_pricing_needed','audit_exports_unpriced':'audit_compliance_need_detected','value_created_unmonetized':'high_value_created_detected'}.get(s.get('leakage_type'), 'renewal_pricing_adjustment_needed')
            opportunities.append({'opportunity_id': f"exp_{s.get('signal_id')}", 'tenant_id': s.get('tenant_id'), 'opportunity_type': kind, 'reason': s.get('reason'), 'supporting_metrics': s.get('supporting_metrics', {}), 'recommended_action': s.get('recommended_action'), 'created_at': s.get('created_at')})
        return opportunities
