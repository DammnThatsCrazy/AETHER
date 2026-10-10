"""Agent communication observability — entity extraction models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class ExtractedEntityType(str, Enum):
    OTP = "otp"
    INVOICE = "invoice"
    RECEIPT = "receipt"
    CALENDAR_INTENT = "calendar_intent"
    SUPPORT_CASE = "support_case"
    PAYMENT_REFERENCE = "payment_reference"
    AMOUNT = "amount"
    OTHER = "other"


class ExtractedEntityObservedRecord(BaseModel):
    entity_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    attachment_obs_id: Optional[str] = None
    entity_type: ExtractedEntityType
    value_ref: Optional[str] = None
    confidence: Optional[float] = None
    provider_model: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class OTPObservationRecord(BaseModel):
    otp_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    digits: Optional[str] = None
    expiry_hint: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class InvoiceObservationRecord(BaseModel):
    invoice_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    vendor: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    due_date: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class ReceiptObservationRecord(BaseModel):
    receipt_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    transacted_at: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class CalendarIntentObservedRecord(BaseModel):
    intent_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    action: Optional[str] = None
    title: Optional[str] = None
    start_hint: Optional[str] = None
    participants: list[str] = Field(default_factory=list)
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class SupportRoutingObservedRecord(BaseModel):
    routing_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    assigned_queue: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
