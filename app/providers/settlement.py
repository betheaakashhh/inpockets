"""Settlement report provider abstraction, vendor-neutral.

A settlement report is the provider's/bank's own list of what it settled on a
day. It is the independent side of reconciliation: we compare it with our
records and never edit either side to make them agree.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class SettlementProviderError(Exception):
    pass


class SettlementUnavailable(SettlementProviderError):
    """The report could not be fetched (down, timed out, not published yet).
    Safe to retry later; nothing is recorded."""


class SettlementReportMalformed(SettlementProviderError):
    """The report is unusable. Nothing from it is trusted or recorded."""


@dataclass(frozen=True)
class SettlementLine:
    line_id: str  # the provider's own id for this settlement line
    provider_ref: str  # the reference we hold on the payment / payout
    amount: Decimal
    status: str  # SETTLED | FAILED | REVERSED


class SettlementProvider(ABC):
    name: str

    @abstractmethod
    async def fetch_report(self, *, flow: str, report_date: date) -> list[SettlementLine]:
        """Every settlement line for `flow` (COLLECTION or DISBURSEMENT) on the
        Indian calendar day `report_date`."""
