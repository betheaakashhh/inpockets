from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PricingVersionCreateRequest(BaseModel):
    """Percentages are plain numbers (36 means 36%). Late charges default to
    KreditBee's format and stay OFF until the lender switches them on."""

    model_config = ConfigDict(extra="forbid")

    effective_from: date
    annual_interest_percent: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    processing_fee_percent: Decimal = Field(ge=0, le=25, max_digits=7, decimal_places=4)
    gst_percent: Decimal = Field(default=Decimal("18"), ge=0, le=50, max_digits=7, decimal_places=4)
    late_charges_enabled: bool = False
    bounce_percent: Decimal = Field(default=Decimal("4"), ge=0, le=100, max_digits=7, decimal_places=4)
    bounce_cap_amount: Decimal = Field(default=Decimal("500"), ge=0, max_digits=12, decimal_places=2)
    penal_annual_percent: Decimal = Field(
        default=Decimal("36"), ge=0, le=100, max_digits=7, decimal_places=4
    )
    penal_max_days: int = Field(default=180, ge=1, le=365)
    late_total_cap_percent_of_due: Decimal = Field(
        default=Decimal("40"), gt=0, le=100, max_digits=7, decimal_places=4
    )
    note: str | None = Field(default=None, max_length=1000)


class PricingRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class PricingVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    status: str
    effective_from: date
    annual_interest_percent: Decimal
    processing_fee_percent: Decimal
    gst_percent: Decimal
    late_charges_enabled: bool
    bounce_percent: Decimal
    bounce_cap_amount: Decimal
    penal_annual_percent: Decimal
    penal_max_days: int
    late_total_cap_percent_of_due: Decimal
    note: str | None
    reject_reason: str | None
    decided_at: datetime | None
    created_at: datetime
